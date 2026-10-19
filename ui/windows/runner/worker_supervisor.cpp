#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "worker_supervisor.h"
#include "native_launch_configuration.h"
#include "preview_lease_bookkeeping.h"

#include <windows.h>
#include <aclapi.h>
#include <sddl.h>
#include <shlobj.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <cwctype>
#include <deque>
#include <functional>
#include <initializer_list>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace chasteady {
namespace {

constexpr size_t kMaxProtocolLineBytes = 1024 * 1024;
constexpr DWORD kPipePollMilliseconds = 12;
constexpr DWORD kFileAccessAll = 0x001F01FF;
constexpr DWORD kDirectoryInheritFlags = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
constexpr char kDefaultErrorMessage[] = "The private worker session could not be completed.";

bool IsValidHandle(HANDLE handle) {
  return handle != nullptr && handle != INVALID_HANDLE_VALUE;
}

class ScopedHandle final {
 public:
  explicit ScopedHandle(HANDLE handle = INVALID_HANDLE_VALUE) noexcept : handle_(handle) {}
  ~ScopedHandle() { reset(); }
  ScopedHandle(const ScopedHandle&) = delete;
  ScopedHandle& operator=(const ScopedHandle&) = delete;
  ScopedHandle(ScopedHandle&& other) noexcept : handle_(other.release()) {}
  ScopedHandle& operator=(ScopedHandle&& other) noexcept {
    if (this != &other) reset(other.release());
    return *this;
  }
  HANDLE get() const noexcept { return handle_; }
  HANDLE release() noexcept {
    HANDLE value = handle_;
    handle_ = INVALID_HANDLE_VALUE;
    return value;
  }
  void reset(HANDLE handle = INVALID_HANDLE_VALUE) noexcept {
    if (IsValidHandle(handle_)) CloseHandle(handle_);
    handle_ = handle;
  }
 private:
  HANDLE handle_;
};

WorkerFailure Failure(std::string code,
                      std::string key,
                      std::string message = kDefaultErrorMessage) {
  WorkerFailure failure;
  failure.code = std::move(code);
  failure.message_key = std::move(key);
  failure.message = std::move(message);
  return failure;
}

bool IsValidUtf8(const std::string& value) {
  const auto* bytes = reinterpret_cast<const unsigned char*>(value.data());
  size_t index = 0;
  while (index < value.size()) {
    const unsigned char first = bytes[index++];
    if (first <= 0x7f) continue;
    uint32_t code_point = 0;
    size_t continuation_count = 0;
    if (first >= 0xc2 && first <= 0xdf) {
      code_point = first & 0x1f;
      continuation_count = 1;
    } else if (first >= 0xe0 && first <= 0xef) {
      code_point = first & 0x0f;
      continuation_count = 2;
    } else if (first >= 0xf0 && first <= 0xf4) {
      code_point = first & 0x07;
      continuation_count = 3;
    } else {
      return false;
    }
    if (index + continuation_count > value.size()) return false;
    for (size_t part = 0; part < continuation_count; ++part) {
      const unsigned char next = bytes[index++];
      if ((next & 0xc0) != 0x80) return false;
      code_point = (code_point << 6) | (next & 0x3f);
    }
    if ((continuation_count == 1 && code_point < 0x80) ||
        (continuation_count == 2 && code_point < 0x800) ||
        (continuation_count == 3 && code_point < 0x10000) ||
        (code_point >= 0xd800 && code_point <= 0xdfff) ||
        code_point > 0x10ffff) {
      return false;
    }
  }
  return true;
}

void AppendUtf8(uint32_t code_point, std::string* output) {
  if (code_point <= 0x7f) {
    output->push_back(static_cast<char>(code_point));
  } else if (code_point <= 0x7ff) {
    output->push_back(static_cast<char>(0xc0 | (code_point >> 6)));
    output->push_back(static_cast<char>(0x80 | (code_point & 0x3f)));
  } else if (code_point <= 0xffff) {
    output->push_back(static_cast<char>(0xe0 | (code_point >> 12)));
    output->push_back(static_cast<char>(0x80 | ((code_point >> 6) & 0x3f)));
    output->push_back(static_cast<char>(0x80 | (code_point & 0x3f)));
  } else {
    output->push_back(static_cast<char>(0xf0 | (code_point >> 18)));
    output->push_back(static_cast<char>(0x80 | ((code_point >> 12) & 0x3f)));
    output->push_back(static_cast<char>(0x80 | ((code_point >> 6) & 0x3f)));
    output->push_back(static_cast<char>(0x80 | (code_point & 0x3f)));
  }
}

struct JsonValue final {
  enum class Type { kNull, kBoolean, kNumber, kString, kArray, kObject };
  Type type = Type::kNull;
  bool boolean = false;
  std::string text;
  std::vector<JsonValue> array;
  std::map<std::string, JsonValue> object;
};

class JsonParser final {
 public:
  explicit JsonParser(const std::string& input) : input_(input) {}

  bool Parse(JsonValue* value) {
    if (value == nullptr || input_.size() > kMaxProtocolLineBytes ||
        !IsValidUtf8(input_)) {
      return false;
    }
    SkipWhitespace();
    if (!ParseValue(value, 0)) return false;
    SkipWhitespace();
    return position_ == input_.size();
  }

 private:
  void SkipWhitespace() {
    while (position_ < input_.size()) {
      const char value = input_[position_];
      if (value != ' ' && value != '\t' && value != '\r' && value != '\n') break;
      ++position_;
    }
  }

  bool ParseValue(JsonValue* value, size_t depth) {
    if (depth > 16 || position_ >= input_.size()) return false;
    switch (input_[position_]) {
      case 'n':
        if (!ConsumeLiteral("null")) return false;
        value->type = JsonValue::Type::kNull;
        return true;
      case 't':
        if (!ConsumeLiteral("true")) return false;
        value->type = JsonValue::Type::kBoolean;
        value->boolean = true;
        return true;
      case 'f':
        if (!ConsumeLiteral("false")) return false;
        value->type = JsonValue::Type::kBoolean;
        value->boolean = false;
        return true;
      case '"':
        value->type = JsonValue::Type::kString;
        return ParseString(&value->text);
      case '[':
        return ParseArray(value, depth);
      case '{':
        return ParseObject(value, depth);
      default:
        return ParseNumber(value);
    }
  }

  bool ConsumeLiteral(const char* literal) {
    const size_t length = std::strlen(literal);
    if (position_ + length > input_.size() ||
        input_.compare(position_, length, literal) != 0) {
      return false;
    }
    position_ += length;
    return true;
  }

  bool ParseHexQuad(uint32_t* value) {
    if (position_ + 4 > input_.size()) return false;
    uint32_t result = 0;
    for (size_t i = 0; i < 4; ++i) {
      const char ch = input_[position_++];
      uint32_t digit = 0;
      if (ch >= '0' && ch <= '9') digit = static_cast<uint32_t>(ch - '0');
      else if (ch >= 'a' && ch <= 'f') digit = static_cast<uint32_t>(ch - 'a' + 10);
      else if (ch >= 'A' && ch <= 'F') digit = static_cast<uint32_t>(ch - 'A' + 10);
      else return false;
      result = (result << 4) | digit;
    }
    *value = result;
    return true;
  }

  bool ParseString(std::string* output) {
    if (position_ >= input_.size() || input_[position_++] != '"') return false;
    output->clear();
    while (position_ < input_.size()) {
      const unsigned char byte = static_cast<unsigned char>(input_[position_++]);
      if (byte == '"') return true;
      if (byte < 0x20) return false;
      if (byte != '\\') {
        output->push_back(static_cast<char>(byte));
        continue;
      }
      if (position_ >= input_.size()) return false;
      const char escaped = input_[position_++];
      switch (escaped) {
        case '"': output->push_back('"'); break;
        case '\\': output->push_back('\\'); break;
        case '/': output->push_back('/'); break;
        case 'b': output->push_back('\b'); break;
        case 'f': output->push_back('\f'); break;
        case 'n': output->push_back('\n'); break;
        case 'r': output->push_back('\r'); break;
        case 't': output->push_back('\t'); break;
        case 'u': {
          uint32_t code_point = 0;
          if (!ParseHexQuad(&code_point)) return false;
          if (code_point >= 0xd800 && code_point <= 0xdbff) {
            if (position_ + 2 > input_.size() || input_[position_] != '\\' ||
                input_[position_ + 1] != 'u') {
              return false;
            }
            position_ += 2;
            uint32_t low = 0;
            if (!ParseHexQuad(&low) || low < 0xdc00 || low > 0xdfff) return false;
            code_point = 0x10000 + ((code_point - 0xd800) << 10) + (low - 0xdc00);
          } else if (code_point >= 0xdc00 && code_point <= 0xdfff) {
            return false;
          }
          AppendUtf8(code_point, output);
          break;
        }
        default: return false;
      }
    }
    return false;
  }

  bool ParseArray(JsonValue* value, size_t depth) {
    ++position_;
    value->type = JsonValue::Type::kArray;
    value->array.clear();
    SkipWhitespace();
    if (position_ < input_.size() && input_[position_] == ']') {
      ++position_;
      return true;
    }
    while (value->array.size() <= kMaxProtocolLineBytes / 2) {
      JsonValue item;
      if (!ParseValue(&item, depth + 1)) return false;
      value->array.push_back(std::move(item));
      SkipWhitespace();
      if (position_ >= input_.size()) return false;
      if (input_[position_] == ']') {
        ++position_;
        return true;
      }
      if (input_[position_++] != ',') return false;
      SkipWhitespace();
    }
    return false;
  }

  bool ParseObject(JsonValue* value, size_t depth) {
    ++position_;
    value->type = JsonValue::Type::kObject;
    value->object.clear();
    SkipWhitespace();
    if (position_ < input_.size() && input_[position_] == '}') {
      ++position_;
      return true;
    }
    while (value->object.size() <= 4096) {
      std::string key;
      if (!ParseString(&key)) return false;
      SkipWhitespace();
      if (position_ >= input_.size() || input_[position_++] != ':') return false;
      SkipWhitespace();
      JsonValue item;
      if (!ParseValue(&item, depth + 1)) return false;
      if (!value->object.emplace(std::move(key), std::move(item)).second) return false;
      SkipWhitespace();
      if (position_ >= input_.size()) return false;
      if (input_[position_] == '}') {
        ++position_;
        return true;
      }
      if (input_[position_++] != ',') return false;
      SkipWhitespace();
    }
    return false;
  }

  bool ParseNumber(JsonValue* value) {
    const size_t start = position_;
    if (position_ < input_.size() && input_[position_] == '-') ++position_;
    if (position_ >= input_.size()) return false;
    if (input_[position_] == '0') {
      ++position_;
      if (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9') return false;
    } else {
      if (input_[position_] < '1' || input_[position_] > '9') return false;
      while (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9') ++position_;
    }
    if (position_ < input_.size() && input_[position_] == '.') {
      ++position_;
      const size_t digits = position_;
      while (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9') ++position_;
      if (digits == position_) return false;
    }
    if (position_ < input_.size() && (input_[position_] == 'e' || input_[position_] == 'E')) {
      ++position_;
      if (position_ < input_.size() && (input_[position_] == '+' || input_[position_] == '-')) ++position_;
      const size_t digits = position_;
      while (position_ < input_.size() && input_[position_] >= '0' && input_[position_] <= '9') ++position_;
      if (digits == position_) return false;
    }
    value->type = JsonValue::Type::kNumber;
    value->text = input_.substr(start, position_ - start);
    return true;
  }

  const std::string& input_;
  size_t position_ = 0;
};

const JsonValue* Member(const JsonValue& object, const char* key) {
  if (object.type != JsonValue::Type::kObject) return nullptr;
  const auto found = object.object.find(key);
  return found == object.object.end() ? nullptr : &found->second;
}

bool HasExactKeys(const JsonValue& value, std::initializer_list<const char*> keys) {
  if (value.type != JsonValue::Type::kObject || value.object.size() != keys.size()) return false;
  for (const char* key : keys) {
    if (value.object.find(key) == value.object.end()) return false;
  }
  return true;
}

bool JsonString(const JsonValue* value, std::string* output) {
  if (value == nullptr || value->type != JsonValue::Type::kString || output == nullptr) return false;
  *output = value->text;
  return true;
}

bool JsonBoolean(const JsonValue* value, bool* output) {
  if (value == nullptr || value->type != JsonValue::Type::kBoolean || output == nullptr) return false;
  *output = value->boolean;
  return true;
}

bool JsonUnsigned(const JsonValue* value, uint64_t* output) {
  if (value == nullptr || value->type != JsonValue::Type::kNumber || output == nullptr ||
      value->text.empty() || value->text.front() == '-') return false;
  if (value->text.find_first_of(".eE") != std::string::npos) return false;
  uint64_t parsed = 0;
  const auto conversion = std::from_chars(value->text.data(), value->text.data() + value->text.size(), parsed);
  if (conversion.ec != std::errc() || conversion.ptr != value->text.data() + value->text.size()) return false;
  *output = parsed;
  return true;
}

void AppendJsonQuoted(const std::string& value, std::string* output) {
  static constexpr char kHex[] = "0123456789abcdef";
  output->push_back('"');
  for (const unsigned char byte : value) {
    switch (byte) {
      case '"': output->append("\\\""); break;
      case '\\': output->append("\\\\"); break;
      case '\b': output->append("\\b"); break;
      case '\f': output->append("\\f"); break;
      case '\n': output->append("\\n"); break;
      case '\r': output->append("\\r"); break;
      case '\t': output->append("\\t"); break;
      default:
        if (byte < 0x20) {
          output->append("\\u00");
          output->push_back(kHex[(byte >> 4) & 0xf]);
          output->push_back(kHex[byte & 0xf]);
        } else {
          output->push_back(static_cast<char>(byte));
        }
    }
  }
  output->push_back('"');
}

void AppendJson(const JsonValue& value, std::string* output) {
  switch (value.type) {
    case JsonValue::Type::kNull: output->append("null"); break;
    case JsonValue::Type::kBoolean: output->append(value.boolean ? "true" : "false"); break;
    case JsonValue::Type::kNumber: output->append(value.text); break;
    case JsonValue::Type::kString: AppendJsonQuoted(value.text, output); break;
    case JsonValue::Type::kArray: {
      output->push_back('[');
      bool first = true;
      for (const auto& item : value.array) {
        if (!first) output->push_back(',');
        first = false;
        AppendJson(item, output);
      }
      output->push_back(']');
      break;
    }
    case JsonValue::Type::kObject: {
      output->push_back('{');
      bool first = true;
      for (const auto& item : value.object) {
        if (!first) output->push_back(',');
        first = false;
        AppendJsonQuoted(item.first, output);
        output->push_back(':');
        AppendJson(item.second, output);
      }
      output->push_back('}');
      break;
    }
  }
}

std::string SerializeJson(const JsonValue& value) {
  std::string result;
  result.reserve(128);
  AppendJson(value, &result);
  return result;
}

std::string QuoteProtocolString(const std::string& value) {
  std::string encoded;
  encoded.reserve(value.size() + 2);
  AppendJsonQuoted(value, &encoded);
  return encoded;
}

bool IsAsciiToken(const std::string& value, size_t min_length, size_t max_length) {
  if (value.size() < min_length || value.size() > max_length) return false;
  for (const unsigned char byte : value) {
    if (!((byte >= 'A' && byte <= 'Z') || (byte >= 'a' && byte <= 'z') ||
          (byte >= '0' && byte <= '9') || byte == '_' || byte == '-' ||
          byte == '.' || byte == ':')) {
      return false;
    }
  }
  return true;
}

bool IsCanonicalUuid(const std::string& value) {
  if (value.size() != 36) return false;
  for (size_t index = 0; index < value.size(); ++index) {
    if (index == 8 || index == 13 || index == 18 || index == 23) {
      if (value[index] != '-') return false;
      continue;
    }
    const char ch = value[index];
    if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) return false;
  }
  return true;
}

bool IsSafeTypedArgs(const JsonValue& value) {
  if (value.type == JsonValue::Type::kString) {
    const std::string& text = value.text;
    if (text.find(":\\") != std::string::npos || text.find(":/") != std::string::npos ||
        text.rfind("\\\\", 0) == 0 || text.rfind("//", 0) == 0) {
      return false;
    }
  } else if (value.type == JsonValue::Type::kArray) {
    for (const auto& item : value.array) if (!IsSafeTypedArgs(item)) return false;
  } else if (value.type == JsonValue::Type::kObject) {
    for (const auto& item : value.object) if (!IsSafeTypedArgs(item.second)) return false;
  }
  return true;
}

bool IsDriveAbsolute(const std::wstring& value) {
  if (value.size() < 3 || value[1] != L':' || (value[2] != L'\\' && value[2] != L'/')) return false;
  if (!((value[0] >= L'A' && value[0] <= L'Z') || (value[0] >= L'a' && value[0] <= L'z'))) return false;
  if (value.rfind(L"\\\\", 0) == 0 || value.rfind(L"\\\\?\\", 0) == 0 ||
      value.rfind(L"\\\\.\\", 0) == 0) return false;
  return true;
}

bool GetFullPath(const std::wstring& value, std::wstring* output) {
  if (output == nullptr || value.empty()) return false;
  std::vector<wchar_t> buffer(512);
  for (;;) {
    const DWORD length = GetFullPathNameW(value.c_str(), static_cast<DWORD>(buffer.size()),
                                          buffer.data(), nullptr);
    if (length == 0) return false;
    if (length < buffer.size()) {
      output->assign(buffer.data(), length);
      return IsDriveAbsolute(*output);
    }
    if (length >= 32767) return false;
    buffer.resize(static_cast<size_t>(length) + 1);
  }
}

bool GetModulePath(std::wstring* output) {
  std::vector<wchar_t> buffer(512);
  for (;;) {
    const DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (length == 0) return false;
    if (length < buffer.size() - 1) {
      std::wstring full;
      if (!GetFullPath(std::wstring(buffer.data(), length), &full)) return false;
      *output = std::move(full);
      return true;
    }
    if (buffer.size() >= 32767) return false;
    buffer.resize(std::min<size_t>(buffer.size() * 2, 32767));
  }
}

std::atomic<uint64_t> g_owned_worker_generation{1};

struct OwnedProcessIdentity final {
  DWORD pid = 0;
  uint64_t creation_filetime = 0;
  std::wstring image;
};

bool CanonicalProcessImage(const std::wstring& value, std::wstring* output) {
  std::wstring full;
  if (!GetFullPath(value, &full)) return false;
  std::vector<wchar_t> buffer(32768);
  const DWORD length = GetLongPathNameW(full.c_str(), buffer.data(), static_cast<DWORD>(buffer.size()));
  if (length == 0 || length >= buffer.size()) return false;
  output->assign(buffer.data(), length);
  return true;
}

bool ReadOwnedProcessIdentity(HANDLE process, OwnedProcessIdentity* identity) {
  if (!IsValidHandle(process) || identity == nullptr) return false;
  FILETIME created{}, exited{}, kernel{}, user{};
  identity->pid = GetProcessId(process);
  if (identity->pid == 0 || !GetProcessTimes(process, &created, &exited, &kernel, &user)) return false;
  identity->creation_filetime = (static_cast<uint64_t>(created.dwHighDateTime) << 32) | created.dwLowDateTime;
  std::vector<wchar_t> image(32768);
  DWORD length = static_cast<DWORD>(image.size());
  if (identity->creation_filetime == 0 || !QueryFullProcessImageNameW(process, 0, image.data(), &length)) return false;
  return CanonicalProcessImage(std::wstring(image.data(), length), &identity->image);
}

// 此对象只持有本次 CreateProcess 原始对象的 duplicate；Stop 清理线程可安全共享其生命周期。
struct OwnedProcessWitness final {
  ScopedHandle process;
  OwnedProcessIdentity identity;
  uint64_t generation = 0;
  std::shared_ptr<std::atomic<bool>> forced_cleanup;

  OwnedWorkerProcessObservation Observe() const {
    OwnedWorkerProcessObservation result;
    result.generation = generation;
    result.pid = identity.pid;
    result.creation_filetime = identity.creation_filetime;
    result.image = identity.image;
    result.identity_verified = true;
    result.forced_cleanup_requested = forced_cleanup->load(std::memory_order_acquire);
    if (!IsValidHandle(process.get())) return result;
    result.original_handle_observed = true;
    const DWORD wait = WaitForSingleObject(process.get(), 0);
    if (wait == WAIT_OBJECT_0) {
      result.wait_state = OwnedWorkerProcessObservation::WaitState::kSignaled;
      DWORD exit_code = STILL_ACTIVE;
      result.exit_code_known = GetExitCodeProcess(process.get(), &exit_code) != FALSE;
      result.exit_code = exit_code;
    } else if (wait == WAIT_TIMEOUT) {
      result.wait_state = OwnedWorkerProcessObservation::WaitState::kLive;
    } else {
      result.wait_state = OwnedWorkerProcessObservation::WaitState::kFailed;
    }
    // 先观测 signaled，再读取强制请求，不能把并发的 Job fallback 误报为自然完成。
    result.forced_cleanup_requested = forced_cleanup->load(std::memory_order_acquire);
    return result;
  }
};

std::wstring ParentPath(const std::wstring& value) {
  const size_t separator = value.find_last_of(L"\\/");
  if (separator == std::wstring::npos || separator < 2) return {};
  return value.substr(0, separator);
}

bool GetCurrentSid(std::wstring* sid_string, std::vector<uint8_t>* sid_bytes) {
  if (sid_string == nullptr || sid_bytes == nullptr) return false;
  ScopedHandle token;
  HANDLE raw_token = INVALID_HANDLE_VALUE;
  if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &raw_token)) return false;
  token.reset(raw_token);
  DWORD needed = 0;
  GetTokenInformation(token.get(), TokenUser, nullptr, 0, &needed);
  if (needed == 0 || needed > 1024 * 1024) return false;
  std::vector<uint8_t> buffer(needed);
  if (!GetTokenInformation(token.get(), TokenUser, buffer.data(), needed, &needed)) return false;
  const auto* user = reinterpret_cast<const TOKEN_USER*>(buffer.data());
  LPWSTR string_sid = nullptr;
  if (!ConvertSidToStringSidW(user->User.Sid, &string_sid) || string_sid == nullptr) return false;
  sid_string->assign(string_sid);
  LocalFree(string_sid);
  const DWORD sid_length = GetLengthSid(user->User.Sid);
  sid_bytes->assign(reinterpret_cast<const uint8_t*>(user->User.Sid),
                    reinterpret_cast<const uint8_t*>(user->User.Sid) + sid_length);
  return !sid_string->empty();
}

std::wstring LocalAppDataPath() {
  std::vector<wchar_t> buffer(32768, L'\0');
  const HRESULT result = SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE,
                                          nullptr, SHGFP_TYPE_CURRENT, buffer.data());
  if (FAILED(result) || buffer[0] == L'\0') return {};
  std::wstring full;
  return GetFullPath(buffer.data(), &full) ? full : std::wstring();
}

std::wstring JoinPath(const std::wstring& parent, const std::wstring& child) {
  if (parent.empty() || child.empty()) return {};
  std::wstring result = parent;
  if (result.back() != L'\\' && result.back() != L'/') result.push_back(L'\\');
  result.append(child);
  return result;
}

bool CheckPathComponents(const std::wstring& path,
                         bool include_leaf,
                         bool allow_missing_leaf) {
  std::wstring full;
  if (!GetFullPath(path, &full)) return false;
  std::wstring current = full.substr(0, 3);
  DWORD attributes = GetFileAttributesW(current.c_str());
  if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
      (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0) {
    return false;
  }
  size_t position = 3;
  std::vector<std::wstring> parts;
  while (position < full.size()) {
    while (position < full.size() && (full[position] == L'\\' || full[position] == L'/')) ++position;
    if (position >= full.size()) break;
    const size_t end = full.find_first_of(L"\\/", position);
    parts.push_back(full.substr(position, end == std::wstring::npos ? end : end - position));
    if (end == std::wstring::npos) break;
    position = end + 1;
  }
  if (!include_leaf && !parts.empty()) parts.pop_back();
  for (size_t i = 0; i < parts.size(); ++i) {
    current = JoinPath(current, parts[i]);
    attributes = GetFileAttributesW(current.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES) {
      const DWORD error = GetLastError();
      return allow_missing_leaf && i + 1 == parts.size() &&
             (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND);
    }
    if ((attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
        (i + 1 < parts.size() && (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0)) return false;
  }
  return true;
}

std::wstring BuildPrivateDataRoot(const std::wstring& sid) {
  const std::wstring local = LocalAppDataPath();
  const DWORD local_attributes = local.empty() ? INVALID_FILE_ATTRIBUTES :
      GetFileAttributesW(local.c_str());
  if (local.empty() || local_attributes == INVALID_FILE_ATTRIBUTES ||
      (local_attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != FILE_ATTRIBUTE_DIRECTORY ||
      !CheckPathComponents(local, true, false)) return {};
  std::wstring parent = JoinPath(JoinPath(local, L"ChaSteady"), L"Users");
  parent = JoinPath(parent, sid);
  const std::array<std::wstring, 3> directories = {
      JoinPath(local, L"ChaSteady"),
      JoinPath(JoinPath(local, L"ChaSteady"), L"Users"),
      parent,
  };
  for (const auto& directory : directories) {
    if (!CheckPathComponents(directory, true, true)) return {};
    DWORD attributes = GetFileAttributesW(directory.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES) {
      if (GetLastError() != ERROR_FILE_NOT_FOUND && GetLastError() != ERROR_PATH_NOT_FOUND) return {};
      if (!CreateDirectoryW(directory.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return {};
      attributes = GetFileAttributesW(directory.c_str());
    }
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0 ||
        (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) return {};
  }
  return JoinPath(parent, L"DesktopData");
}

std::wstring BuildPrivateSddl(const std::wstring& sid) {
  return L"D:P(A;OICI;FA;;;" + sid + L")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)";
}

bool HasExpectedPrivateAcl(const std::wstring& path, PSID user_sid) {
  PSID owner = nullptr;
  PACL dacl = nullptr;
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  const DWORD status = GetNamedSecurityInfoW(const_cast<LPWSTR>(path.c_str()), SE_FILE_OBJECT,
      OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
      &owner, nullptr, &dacl, nullptr, &descriptor);
  if (status != ERROR_SUCCESS || descriptor == nullptr || dacl == nullptr || owner == nullptr) {
    if (descriptor != nullptr) LocalFree(descriptor);
    return false;
  }
  PSID system_sid = nullptr;
  PSID admins_sid = nullptr;
  SID_IDENTIFIER_AUTHORITY nt_authority = SECURITY_NT_AUTHORITY;
  const bool allocated_system = AllocateAndInitializeSid(&nt_authority, 1,
      SECURITY_LOCAL_SYSTEM_RID, 0, 0, 0, 0, 0, 0, 0, &system_sid) != FALSE;
  const bool allocated_admins = AllocateAndInitializeSid(&nt_authority, 2,
      SECURITY_BUILTIN_DOMAIN_RID, DOMAIN_ALIAS_RID_ADMINS, 0, 0, 0, 0, 0, 0,
      &admins_sid) != FALSE;
  SECURITY_DESCRIPTOR_CONTROL control = 0;
  DWORD revision = 0;
  bool valid = allocated_system && allocated_admins &&
               GetSecurityDescriptorControl(descriptor, &control, &revision) &&
               (control & SE_DACL_PROTECTED) != 0 && EqualSid(owner, user_sid) &&
               dacl->AceCount == 3;
  bool saw_user = false;
  bool saw_system = false;
  bool saw_admins = false;
  for (DWORD index = 0; valid && index < dacl->AceCount; ++index) {
    void* raw_ace = nullptr;
    if (!GetAce(dacl, index, &raw_ace) || raw_ace == nullptr) {
      valid = false;
      break;
    }
    const auto* header = static_cast<const ACE_HEADER*>(raw_ace);
    if (header->AceType != ACCESS_ALLOWED_ACE_TYPE ||
        header->AceSize < sizeof(ACCESS_ALLOWED_ACE) ||
        (header->AceFlags & kDirectoryInheritFlags) != kDirectoryInheritFlags) {
      valid = false;
      break;
    }
    const auto* ace = static_cast<const ACCESS_ALLOWED_ACE*>(raw_ace);
    PSID ace_sid = const_cast<DWORD*>(&ace->SidStart);
    if (ace->Mask != kFileAccessAll) {
      valid = false;
    } else if (EqualSid(ace_sid, user_sid) && !saw_user) {
      saw_user = true;
    } else if (EqualSid(ace_sid, system_sid) && !saw_system) {
      saw_system = true;
    } else if (EqualSid(ace_sid, admins_sid) && !saw_admins) {
      saw_admins = true;
    } else {
      valid = false;
    }
  }
  valid = valid && saw_user && saw_system && saw_admins;
  if (allocated_system) FreeSid(system_sid);
  if (allocated_admins) FreeSid(admins_sid);
  LocalFree(descriptor);
  return valid;
}

bool EnsurePrivateDataRoot(const std::wstring& path,
                           const std::wstring& sid_string,
                           PSID user_sid) {
  if (path.empty() || !CheckPathComponents(ParentPath(path), true, false)) return false;
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  const std::wstring sddl = BuildPrivateSddl(sid_string);
  if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                                                             &descriptor, nullptr)) return false;
  SECURITY_ATTRIBUTES attributes{};
  attributes.nLength = sizeof(attributes);
  attributes.lpSecurityDescriptor = descriptor;
  attributes.bInheritHandle = FALSE;
  const BOOL created = CreateDirectoryW(path.c_str(), &attributes);
  const DWORD create_error = created ? ERROR_SUCCESS : GetLastError();
  LocalFree(descriptor);
  if (!created && create_error != ERROR_ALREADY_EXISTS) return false;
  const DWORD root_attributes = GetFileAttributesW(path.c_str());
  if (root_attributes == INVALID_FILE_ATTRIBUTES ||
      (root_attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != FILE_ATTRIBUTE_DIRECTORY ||
      !CheckPathComponents(path, true, false)) return false;
  return HasExpectedPrivateAcl(path, user_sid);
}

bool GetCurrentSidAndString(std::wstring* sid_string,
                            std::vector<uint8_t>* sid_buffer) {
  return GetCurrentSid(sid_string, sid_buffer);
}

bool IsDisjoint(const std::wstring& bundle, const std::wstring& data) {
  auto normalize = [](std::wstring value) {
    while (value.size() > 3 && (value.back() == L'\\' || value.back() == L'/')) value.pop_back();
    std::transform(value.begin(), value.end(), value.begin(), [](wchar_t ch) {
      return static_cast<wchar_t>(towlower(ch));
    });
    return value;
  };
  const std::wstring left = normalize(bundle);
  const std::wstring right = normalize(data);
  const auto within = [](const std::wstring& parent, const std::wstring& child) {
    return child.size() > parent.size() && child.compare(0, parent.size(), parent) == 0 &&
           (parent.back() == L'\\' || child[parent.size()] == L'\\');
  };
  return left != right && !within(left, right) && !within(right, left);
}

uint64_t HashPath(const std::wstring& path) {
  uint64_t hash = 14695981039346656037ull;
  for (const wchar_t code_unit : path) {
    const uint16_t value = static_cast<uint16_t>(towlower(code_unit));
    hash ^= static_cast<uint8_t>(value & 0xff);
    hash *= 1099511628211ull;
    hash ^= static_cast<uint8_t>((value >> 8) & 0xff);
    hash *= 1099511628211ull;
  }
  return hash;
}

std::wstring Hex64(uint64_t value) {
  static constexpr wchar_t kHex[] = L"0123456789abcdef";
  std::wstring result(16, L'0');
  for (int index = 15; index >= 0; --index) {
    result[static_cast<size_t>(index)] = kHex[value & 0xf];
    value >>= 4;
  }
  return result;
}

std::wstring QuoteWindowsArgument(const std::wstring& argument) {
  std::wstring result = L"\"";
  size_t slashes = 0;
  for (const wchar_t ch : argument) {
    if (ch == L'\\') {
      ++slashes;
      continue;
    }
    if (ch == L'"') {
      result.append(slashes * 2 + 1, L'\\');
      result.push_back(L'"');
      slashes = 0;
      continue;
    }
    result.append(slashes, L'\\');
    slashes = 0;
    result.push_back(ch);
  }
  result.append(slashes * 2, L'\\');
  result.push_back(L'"');
  return result;
}

bool CreateChildDiagnosticFile(const std::wstring& root,
                               const std::wstring& sid,
                               HANDLE* output) {
  if (output == nullptr) return false;
  const std::wstring sddl = L"D:P(A;;FA;;;" + sid + L")(A;;FA;;;SY)(A;;FA;;;BA)";
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                                                             &descriptor, nullptr)) return false;
  SECURITY_ATTRIBUTES attributes{};
  attributes.nLength = sizeof(attributes);
  attributes.lpSecurityDescriptor = descriptor;
  attributes.bInheritHandle = TRUE;
  HANDLE file = INVALID_HANDLE_VALUE;
  const std::wstring stem = L"worker-stderr-" + std::to_wstring(GetCurrentProcessId()) +
      L"-" + std::to_wstring(GetTickCount64());
  for (unsigned int attempt = 0; attempt < 16; ++attempt) {
    const std::wstring filename = stem + L"-" + std::to_wstring(attempt) + L".log";
    const std::wstring path = JoinPath(root, filename);
    file = CreateFileW(path.c_str(), FILE_APPEND_DATA,
        FILE_SHARE_READ, &attributes, CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (IsValidHandle(file)) break;
    const DWORD error = GetLastError();
    if (error != ERROR_FILE_EXISTS && error != ERROR_ALREADY_EXISTS) break;
  }
  LocalFree(descriptor);
  if (!IsValidHandle(file)) return false;
  FILE_ATTRIBUTE_TAG_INFO tag{};
  FILE_STANDARD_INFO standard{};
  BY_HANDLE_FILE_INFORMATION info{};
  const bool valid = GetFileType(file) == FILE_TYPE_DISK &&
      GetFileInformationByHandleEx(file, FileAttributeTagInfo, &tag, sizeof(tag)) &&
      GetFileInformationByHandleEx(file, FileStandardInfo, &standard, sizeof(standard)) &&
      GetFileInformationByHandle(file, &info) &&
      (tag.FileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) == 0 &&
      !standard.Directory && info.nNumberOfLinks == 1;
  if (!valid) {
    CloseHandle(file);
    return false;
  }
  *output = file;
  return true;
}

bool ReadProtocolLine(HANDLE output_pipe,
                      HANDLE process,
                      DWORD timeout_ms,
                      const std::atomic<bool>& stop_requested,
                      const std::function<void()>& on_process_signaled,
                      std::string* buffered,
                      std::string* line,
                      bool* eof) {
  if (buffered == nullptr || line == nullptr || eof == nullptr) return false;
  line->clear();
  *eof = false;
  const ULONGLONG started = GetTickCount64();
  bool process_signaled_handled = false;
  std::array<char, 4096> buffer{};
  for (;;) {
    const size_t newline = buffered->find('\n');
    if (newline != std::string::npos) {
      if (newline + 1 > kMaxProtocolLineBytes) return false;
      line->assign(buffered->data(), newline);
      buffered->erase(0, newline + 1);
      if (!line->empty() && line->back() == '\r') line->pop_back();
      if (line->find('\r') != std::string::npos) return false;
      return true;
    }
    if (buffered->size() > kMaxProtocolLineBytes) return false;
    if (stop_requested.load(std::memory_order_acquire)) return false;
    DWORD available = 0;
    if (!PeekNamedPipe(output_pipe, nullptr, 0, nullptr, &available, nullptr)) {
      const DWORD error = GetLastError();
      if (error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA || error == ERROR_PIPE_NOT_CONNECTED) {
        *eof = true;
        return buffered->empty();
      }
      if (error == ERROR_OPERATION_ABORTED) return false;
      return false;
    }
    if (available != 0) {
      const DWORD chunk = std::min<DWORD>(available, static_cast<DWORD>(buffer.size()));
      DWORD read = 0;
      if (!ReadFile(output_pipe, buffer.data(), chunk, &read, nullptr)) {
        const DWORD error = GetLastError();
        if (error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA || error == ERROR_PIPE_NOT_CONNECTED) {
          *eof = true;
          return buffered->empty();
        }
        return false;
      }
      if (read == 0) {
        *eof = true;
        return buffered->empty();
      }
      buffered->append(buffer.data(), read);
      continue;
    }
    if (!process_signaled_handled && IsValidHandle(process) &&
        WaitForSingleObject(process, 0) == WAIT_OBJECT_0 && on_process_signaled) {
      // Worker.exe may exit while one of its in-job descendants still holds an
      // inherited stdout handle. Close only our own Job Object, then keep
      // reading until the pipe itself reaches EOF.
      process_signaled_handled = true;
      on_process_signaled();
    }
    if (timeout_ms != INFINITE && GetTickCount64() - started >= timeout_ms) return false;
    Sleep(kPipePollMilliseconds);
  }
}

bool DrainPipeUntilEof(HANDLE pipe, HANDLE process, HANDLE job, bool* forced) {
  if (!IsValidHandle(pipe)) return true;
  std::array<char, 4096> buffer{};
  ULONGLONG process_signaled_at = 0;
  bool job_termination_requested = false;
  for (;;) {
    DWORD available = 0;
    if (!PeekNamedPipe(pipe, nullptr, 0, nullptr, &available, nullptr)) {
      const DWORD error = GetLastError();
      return error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA ||
             error == ERROR_PIPE_NOT_CONNECTED;
    }
    if (available != 0) {
      const DWORD count = std::min<DWORD>(available, static_cast<DWORD>(buffer.size()));
      DWORD read = 0;
      if (!ReadFile(pipe, buffer.data(), count, &read, nullptr)) {
        const DWORD error = GetLastError();
        return error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA ||
               error == ERROR_PIPE_NOT_CONNECTED;
      }
      if (read == 0) return false;
      SecureZeroMemory(buffer.data(), read);
      continue;
    }
    if (IsValidHandle(process) && WaitForSingleObject(process, 0) == WAIT_OBJECT_0) {
      const ULONGLONG now = GetTickCount64();
      if (process_signaled_at == 0) process_signaled_at = now;
      if (!job_termination_requested && IsValidHandle(job) && now - process_signaled_at >= 250) {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
        if (!QueryInformationJobObject(job, JobObjectBasicAccountingInformation,
                                       &accounting, sizeof(accounting), nullptr) ||
            accounting.ActiveProcesses != 0 || now - process_signaled_at >= 3000) {
          TerminateJobObject(job, ERROR_CANCELLED);
          job_termination_requested = true;
          if (forced != nullptr) *forced = true;
        }
      } else if (!IsValidHandle(job) && now - process_signaled_at >= 2000 && forced != nullptr) {
        // In startup-cancel cleanup, Stop's bounded owned-job closer is the
        // fallback. EOF taking longer than it does indicates that fallback ran.
        *forced = true;
      }
    }
    Sleep(kPipePollMilliseconds);
  }
}

bool ValidateOrigin(const std::string& origin) {
  const std::string prefix = "http://127.0.0.1:";
  if (origin.rfind(prefix, 0) != 0) return false;
  const std::string port_text = origin.substr(prefix.size());
  if (port_text.empty() || port_text.size() > 5 || port_text.front() == '0') return false;
  uint32_t port = 0;
  for (const char digit : port_text) {
    if (digit < '0' || digit > '9') return false;
    port = port * 10 + static_cast<uint32_t>(digit - '0');
  }
  return port >= 1 && port <= 65535 && origin == prefix + std::to_string(port);
}

void ZeroJsonStringField(JsonValue* value, const char* key) {
  if (value == nullptr || value->type != JsonValue::Type::kObject) return;
  const auto found = value->object.find(key);
  if (found != value->object.end() && found->second.type == JsonValue::Type::kString &&
      !found->second.text.empty()) {
    SecureZeroMemory(found->second.text.data(), found->second.text.size());
  }
}

bool ParseReady(const std::string& line,
                DWORD expected_pid,
                WorkerReady* ready,
                std::string* native_capability) {
  if (ready == nullptr || native_capability == nullptr) return false;
  JsonValue root;
  JsonParser parser(line);
  const bool parsed = parser.Parse(&root);
  if (!parsed || !HasExactKeys(root, {"type", "protocol", "pid", "origin", "bearer", "native_capability"})) {
    ZeroJsonStringField(&root, "native_capability");
    return false;
  }
  std::string type;
  std::string origin;
  std::string bearer;
  std::string capability;
  uint64_t protocol = 0;
  uint64_t pid = 0;
  const bool valid = JsonString(Member(root, "type"), &type) && type == "ready" &&
      JsonUnsigned(Member(root, "protocol"), &protocol) && protocol == 1 &&
      JsonUnsigned(Member(root, "pid"), &pid) && pid == expected_pid &&
      JsonString(Member(root, "origin"), &origin) && ValidateOrigin(origin) &&
      JsonString(Member(root, "bearer"), &bearer) && IsAsciiToken(bearer, 24, 256) &&
      JsonString(Member(root, "native_capability"), &capability) &&
      IsAsciiToken(capability, 32, 256);
  ZeroJsonStringField(&root, "native_capability");
  if (!valid) {
    if (!capability.empty()) SecureZeroMemory(capability.data(), capability.size());
    return false;
  }
  ready->origin = std::move(origin);
  ready->bearer = std::move(bearer);
  *native_capability = std::move(capability);
  return true;
}

std::string NewRequestJson(uint64_t id,
                           const std::string& capability,
                           const char* action,
                           const char* extra_key,
                           const std::string& extra_value) {
  const std::string request_id = "native-" + std::to_string(id);
  std::string json = "{\"protocol\":1,\"request_id\":" + QuoteProtocolString(request_id) +
      ",\"capability\":" + QuoteProtocolString(capability) +
      ",\"action\":" + QuoteProtocolString(action);
  if (extra_key != nullptr) {
    json.append(",\"").append(extra_key).append("\":").append(QuoteProtocolString(extra_value));
  }
  json.append("}\n");
  return json;
}

bool ParseErrorEnvelope(const JsonValue& root, WorkerFailure* failure) {
  const JsonValue* error = Member(root, "error");
  if (error == nullptr || !HasExactKeys(*error, {"code", "message_key", "message", "args"})) return false;
  std::string code;
  std::string key;
  std::string message;
  const JsonValue* args = Member(*error, "args");
  if (!JsonString(Member(*error, "code"), &code) || !IsAsciiToken(code, 1, 128) ||
      !JsonString(Member(*error, "message_key"), &key) || !IsAsciiToken(key, 1, 256) ||
      !JsonString(Member(*error, "message"), &message) || message.size() > 8192 ||
      args == nullptr || args->type != JsonValue::Type::kObject) return false;
  failure->code = std::move(code);
  failure->message_key = std::move(key);
  // Typed message_key/args are the user-facing error surface. Do not reflect
  // worker prose into a platform exception where a path or secret could leak.
  failure->message = kDefaultErrorMessage;
  failure->args_json = IsSafeTypedArgs(*args) ? SerializeJson(*args) : "{}";
  return true;
}

}  // namespace

OwnedWorkerHandle::OwnedWorkerHandle(HANDLE handle) noexcept : handle_(handle) {}
OwnedWorkerHandle::~OwnedWorkerHandle() {
  if (IsValidHandle(handle_)) CloseHandle(handle_);
}
OwnedWorkerHandle::OwnedWorkerHandle(OwnedWorkerHandle&& other) noexcept
    : handle_(other.release()) {}
OwnedWorkerHandle& OwnedWorkerHandle::operator=(OwnedWorkerHandle&& other) noexcept {
  if (this != &other) {
    if (IsValidHandle(handle_)) CloseHandle(handle_);
    handle_ = other.release();
  }
  return *this;
}
HANDLE OwnedWorkerHandle::get() const noexcept { return handle_; }
HANDLE OwnedWorkerHandle::release() noexcept {
  HANDLE result = handle_;
  handle_ = INVALID_HANDLE_VALUE;
  return result;
}
OwnedWorkerHandle::operator bool() const noexcept { return IsValidHandle(handle_); }

class WorkerSupervisor::Impl final {
 public:
  explicit Impl(WorkerSupervisorOptions options) : options_(options) {}
  ~Impl() { Stop(); }

  void StartAsync(ReadyCallback callback) {
    if (!callback) return;
    WorkerReady existing_ready;
    WorkerFailure failure;
    bool deliver_ready = false;
    bool deliver_failure = false;
    std::vector<ReadyCallback> failed_callbacks;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (state_ == State::kStarting) {
        ready_callbacks_.push_back(std::move(callback));
        return;
      }
      if (state_ == State::kRunning) {
        existing_ready = ready_;
        deliver_ready = true;
      } else if (state_ == State::kNew) {
        state_ = State::kStarting;
        ready_callbacks_.push_back(std::move(callback));
        try {
          startup_thread_ = std::thread([this] {
            try {
              StartWorker();
            } catch (...) {
              FailStart(Failure("worker_start_failed", "nativeWorker.error.startup"));
            }
          });
        } catch (...) {
          state_ = State::kStopped;
          failure = Failure("worker_start_failed", "nativeWorker.error.startup");
          terminal_failure_ = failure;
          deliver_failure = true;
          failed_callbacks.swap(ready_callbacks_);
        }
      } else {
        failure = terminal_failure_.code.empty()
            ? Failure("worker_stopped", "nativeWorker.error.stopped")
            : terminal_failure_;
        deliver_failure = true;
      }
    }
    if (deliver_ready) {
      DispatchReady(std::move(callback), true, std::move(existing_ready), {});
    } else if (deliver_failure) {
      if (!failed_callbacks.empty()) {
        for (auto& waiting : failed_callbacks) {
          DispatchReady(std::move(waiting), false, {}, failure);
        }
      } else {
        DispatchReady(std::move(callback), false, {}, std::move(failure));
      }
    }
  }

  void GetWebSession(ReplyCallback callback) {
    QueueRequest(Action::kWebSession, {}, std::move(callback));
  }

  void AcquireMedia(const std::string& artifact_id, ReplyCallback callback) {
    if (!IsCanonicalUuid(artifact_id)) {
      DispatchReply(std::move(callback), ErrorReply(
          "invalid_artifact_id", "nativeMedia.error.invalidArtifact"));
      return;
    }
    QueueRequest(Action::kAcquireMedia, artifact_id, std::move(callback));
  }

  void ReleaseMedia(const std::string& lease_id, ReplyCallback callback) {
    if (!IsCanonicalUuid(lease_id)) {
      DispatchReply(std::move(callback), ErrorReply(
          "invalid_lease_id", "nativeMedia.error.invalidLease"));
      return;
    }
    QueueRequest(Action::kReleaseMedia, lease_id, std::move(callback));
  }

  void RequestShutdown(ReplyCallback callback) {
    if (!callback) return;
    bool cancel_startup = false;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      cancel_startup = state_ == State::kNew || state_ == State::kStarting || state_ == State::kStopped;
      if (cancel_startup) stop_requested_.store(true, std::memory_order_release);
    }
    if (!cancel_startup) {
      QueueRequest(Action::kShutdown, {}, std::move(callback));
      return;
    }
    HANDLE process_copy = INVALID_HANDLE_VALUE;
    HANDLE output_copy = INVALID_HANDLE_VALUE;
    bool process_duplicate_ok = true;
    bool output_duplicate_ok = true;
    {
      std::lock_guard<std::mutex> lock(handles_mutex_);
      auto duplicate = [](HANDLE source, HANDLE* target) {
        if (!IsValidHandle(source)) return true;
        return DuplicateHandle(GetCurrentProcess(), source, GetCurrentProcess(), target,
                               0, FALSE, DUPLICATE_SAME_ACCESS) != FALSE;
      };
      process_duplicate_ok = duplicate(process_handle_, &process_copy);
      output_duplicate_ok = duplicate(output_read_, &output_copy);
    }
    Stop();

    bool forced = false;
    bool cleanup_ok = process_duplicate_ok && output_duplicate_ok;
    if (process_duplicate_ok && IsValidHandle(process_copy)) {
      const DWORD wait_ms = std::min<DWORD>(options_.graceful_shutdown_timeout_ms, 2000);
      const DWORD wait = WaitForSingleObject(process_copy, wait_ms);
      if (wait == WAIT_TIMEOUT) {
        forced = true;  // Stop's owned cleanup thread closes the kill-on-close job.
        if (WaitForSingleObject(process_copy, 5000) != WAIT_OBJECT_0) cleanup_ok = false;
      } else if (wait != WAIT_OBJECT_0) {
        cleanup_ok = false;
      }
    }
    if (cleanup_ok && IsValidHandle(output_copy)) {
      cleanup_ok = DrainPipeUntilEof(output_copy, process_copy, INVALID_HANDLE_VALUE, &forced);
    }
    if (IsValidHandle(output_copy)) CloseHandle(output_copy);
    if (IsValidHandle(process_copy)) CloseHandle(process_copy);
    const OwnedWorkerProcessObservation observation = ObserveOwnedProcess();
    if (observation.generation != 0 && !observation.IsVerifiedTerminal() &&
        !observation.HasReapedStartupFailure()) cleanup_ok = false;
    forced = forced || observation.forced_cleanup_requested;

    WorkerReply reply;
    reply.ok = cleanup_ok;
    reply.shutting_down = cleanup_ok;
    reply.shutdown_timed_out = forced;
    if (!cleanup_ok) {
      reply.failure = Failure("worker_cleanup_unconfirmed", "nativeWorker.error.exited");
    }
    DispatchReply(std::move(callback), std::move(reply));
  }

  void SetExitCallback(ExitCallback callback) {
    std::lock_guard<std::mutex> lock(mutex_);
    exit_callback_ = std::move(callback);
  }

  OwnedWorkerProcessObservation ObserveOwnedProcess() const {
    std::shared_ptr<OwnedProcessWitness> witness;
    OwnedWorkerProcessObservation startup_reap;
    uint64_t generation = 0;
    {
      std::lock_guard<std::mutex> lock(handles_mutex_);
      witness = process_witness_;
      generation = process_generation_;
      if (startup_reap_observation_.MatchesReapedStartupFailure(generation, created_worker_pid_,
          ready_ever_published_.load(std::memory_order_acquire))) startup_reap = startup_reap_observation_;
    }
    if (witness) return witness->Observe();
    OwnedWorkerProcessObservation result;
    if (startup_reap.HasReapedStartupFailure()) result = std::move(startup_reap);
    else result.generation = generation;
    result.forced_cleanup_requested = forced_cleanup_requested_->load(std::memory_order_acquire);
    return result;
  }

  bool IsReady() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return state_ == State::kRunning || state_ == State::kShuttingDown;
  }

  void Stop() {
    if (stop_called_.exchange(true, std::memory_order_acq_rel)) return;
    stop_requested_.store(true, std::memory_order_release);
    std::vector<ReadyCallback> ready_callbacks;
    std::vector<ReplyCallback> reply_callbacks;
    WorkerFailure failure = Failure("worker_stopped", "nativeWorker.error.stopped");
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (state_ == State::kStopped) {
        // Thread joins and process-handle release still happen below.
      }
      state_ = State::kStopped;
      stopping_ = true;
      if (terminal_failure_.code.empty()) terminal_failure_ = failure;
      ready_callbacks.swap(ready_callbacks_);
      for (auto& item : pending_) reply_callbacks.push_back(std::move(item.second.callback));
      pending_.clear();
      if (shutdown_callback_) reply_callbacks.push_back(std::move(shutdown_callback_));
      for (auto& item : outbound_) {
        if (!item.line.empty()) SecureZeroMemory(item.line.data(), item.line.size());
      }
      outbound_.clear();
      condition_.notify_all();
    }
    for (auto& callback : ready_callbacks) {
      if (callback) DispatchReady(std::move(callback), false, {}, failure);
    }
    for (auto& callback : reply_callbacks) {
      if (callback) DispatchReply(std::move(callback), ErrorReply(failure));
    }

    JoinThread(startup_thread_);
    CancelAndJoinIoThreads();
    CloseInputPipe();
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (!capability_.empty()) SecureZeroMemory(capability_.data(), capability_.size());
      capability_.clear();
      if (!ready_.bearer.empty()) SecureZeroMemory(ready_.bearer.data(), ready_.bearer.size());
      ready_.bearer.clear();
      if (!pipe_buffer_.empty()) SecureZeroMemory(pipe_buffer_.data(), pipe_buffer_.size());
      pipe_buffer_.clear();
    }

    HANDLE process = INVALID_HANDLE_VALUE;
    HANDLE job = INVALID_HANDLE_VALUE;
    HANDLE mutex = INVALID_HANDLE_VALUE;
    std::shared_ptr<OwnedProcessWitness> witness;
    const auto forced_cleanup = forced_cleanup_requested_;
    {
      std::lock_guard<std::mutex> lock(handles_mutex_);
      process = std::exchange(process_handle_, INVALID_HANDLE_VALUE);
      job = std::exchange(job_handle_, INVALID_HANDLE_VALUE);
      mutex = std::exchange(singleton_mutex_, INVALID_HANDLE_VALUE);
      witness = process_witness_;
      CloseHandleIfValid(output_read_);
      output_read_ = INVALID_HANDLE_VALUE;
    }
    if (IsValidHandle(process) || IsValidHandle(job) || IsValidHandle(mutex)) {
      const DWORD grace = shutdown_acknowledged_.load(std::memory_order_acquire)
          ? options_.graceful_shutdown_timeout_ms
          : std::min<DWORD>(options_.graceful_shutdown_timeout_ms, 2000);
      try {
        std::thread([process, job, mutex, grace, witness, forced_cleanup]() {
          if (IsValidHandle(process)) WaitForSingleObject(process, grace);
          // 仍只关闭原有 owned Job；共享 duplicate 不随原始 handle 转移而失效。
          CloseTransferredJob(job, witness, forced_cleanup);
          if (IsValidHandle(process)) CloseHandle(process);
          if (IsValidHandle(mutex)) CloseHandle(mutex);
        }).detach();
      } catch (...) {
        CloseTransferredJob(job, witness, forced_cleanup);
        if (IsValidHandle(process)) CloseHandle(process);
        if (IsValidHandle(mutex)) CloseHandle(mutex);
      }
    }
  }

 private:
  enum class State { kNew, kStarting, kRunning, kShuttingDown, kStopped };
  enum class Action { kWebSession, kAcquireMedia, kReleaseMedia, kShutdown };

  struct Pending final {
    Action action;
    ReplyCallback callback;
    std::chrono::steady_clock::time_point deadline;
  };

  struct Outbound final {
    Action action;
    std::string request_id;
    std::string line;
  };

  static WorkerReply ErrorReply(std::string code,
                                std::string key,
                                std::string message = kDefaultErrorMessage) {
    return ErrorReply(Failure(std::move(code), std::move(key), std::move(message)));
  }

  static WorkerReply ErrorReply(WorkerFailure failure) {
    WorkerReply reply;
    reply.ok = false;
    reply.failure = std::move(failure);
    return reply;
  }

  static void DispatchReply(ReplyCallback callback, WorkerReply reply) {
    if (!callback) return;
    struct Delivery final {
      ReplyCallback callback;
      WorkerReply reply;
    };
    // Keep the payload outside the thread callable so a failed thread creation
    // leaves an intact callback for the synchronous emergency fallback.
    Delivery* const delivery = new (std::nothrow) Delivery{
        std::move(callback), std::move(reply)};
    if (delivery == nullptr) {
      try { callback(std::move(reply)); } catch (...) {}
      return;
    }

    std::thread dispatcher;
    try {
      dispatcher = std::thread([delivery] {
        std::unique_ptr<Delivery> owned(delivery);
        if (owned->callback) {
          try { owned->callback(std::move(owned->reply)); } catch (...) {}
        }
      });
    } catch (...) {
      std::unique_ptr<Delivery> owned(delivery);
      if (owned->callback) {
        // DispatchReply is called only after supervisor locks are released.
        // Bridge callbacks marshal to the HWND and do not call Flutter here.
        try { owned->callback(std::move(owned->reply)); } catch (...) {}
      }
      return;
    }
    dispatcher.detach();
  }

  static void DispatchReady(ReadyCallback callback,
                            bool ok,
                            WorkerReady ready,
                            WorkerFailure failure) {
    if (!callback) return;
    struct Delivery final {
      ReadyCallback callback;
      bool ok;
      WorkerReady ready;
      WorkerFailure failure;
    };
    Delivery* const delivery = new (std::nothrow) Delivery{
        std::move(callback), ok, std::move(ready), std::move(failure)};
    if (delivery == nullptr) {
      try { callback(ok, std::move(ready), std::move(failure)); } catch (...) {}
      return;
    }
    std::thread dispatcher;
    try {
      dispatcher = std::thread([delivery] {
        std::unique_ptr<Delivery> owned(delivery);
        if (owned->callback) {
          try { owned->callback(owned->ok, std::move(owned->ready),
                                std::move(owned->failure)); } catch (...) {}
        }
      });
    } catch (...) {
      std::unique_ptr<Delivery> owned(delivery);
      // Every DispatchReady call site has released the supervisor mutex.
      if (owned->callback) {
        try { owned->callback(owned->ok, std::move(owned->ready),
                              std::move(owned->failure)); } catch (...) {}
      }
      return;
    }
    dispatcher.detach();
  }

  bool InitializeOwnedProcessWitness(DWORD expected_pid, const std::wstring& expected_image) {
    uint64_t generation = g_owned_worker_generation.load(std::memory_order_relaxed);
    do {
      if (generation == 0 || generation == std::numeric_limits<uint64_t>::max()) return false;
    } while (!g_owned_worker_generation.compare_exchange_weak(generation, generation + 1,
                                                             std::memory_order_relaxed));
    {
      std::lock_guard<std::mutex> lock(handles_mutex_);
      process_generation_ = generation;
      process_witness_.reset();
      startup_reap_observation_ = OwnedWorkerProcessObservation{};
    }
    HANDLE original = GetProcessHandle();
    OwnedProcessIdentity identity;
    std::wstring canonical_expected;
    if (!ReadOwnedProcessIdentity(original, &identity) || identity.pid != expected_pid ||
        !CanonicalProcessImage(expected_image, &canonical_expected) ||
        CompareStringOrdinal(identity.image.c_str(), -1, canonical_expected.c_str(), -1, TRUE) != CSTR_EQUAL)
      return false;
    HANDLE duplicated = INVALID_HANDLE_VALUE;
    if (!DuplicateHandle(GetCurrentProcess(), original, GetCurrentProcess(), &duplicated,
                         SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, 0)) return false;
    ScopedHandle copy(duplicated);
    OwnedProcessIdentity duplicate_identity;
    if (!ReadOwnedProcessIdentity(copy.get(), &duplicate_identity) ||
        duplicate_identity.pid != identity.pid || duplicate_identity.creation_filetime != identity.creation_filetime ||
        duplicate_identity.image != identity.image) return false;
    auto witness = std::make_shared<OwnedProcessWitness>();
    witness->process.reset(copy.release());
    witness->identity = std::move(identity);
    witness->generation = generation;
    witness->forced_cleanup = forced_cleanup_requested_;
    {
      std::lock_guard<std::mutex> lock(handles_mutex_);
      process_witness_ = std::move(witness);
    }
    return true;
  }

  void StartWorker() {
    std::wstring executable;
    std::wstring bundle_root;
    std::wstring data_root;
    std::wstring sid_string;
    std::vector<uint8_t> sid_buffer;
    if (!GetModulePath(&executable)) {
      FailStart(Failure("worker_bundle_unavailable", "nativeWorker.error.bundle"));
      return;
    }
    bundle_root = ParentPath(executable);
    const DWORD bundle_attributes = bundle_root.empty()
        ? INVALID_FILE_ATTRIBUTES : GetFileAttributesW(bundle_root.c_str());
    if (bundle_root.empty() || bundle_attributes == INVALID_FILE_ATTRIBUTES ||
        (bundle_attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != FILE_ATTRIBUTE_DIRECTORY ||
        !CheckPathComponents(bundle_root, true, false)) {
      FailStart(Failure("worker_bundle_unavailable", "nativeWorker.error.bundle"));
      return;
    }
    if (!GetCurrentSidAndString(&sid_string, &sid_buffer)) {
      FailStart(Failure("worker_data_root_unavailable", "nativeWorker.error.dataRoot"));
      return;
    }
    if (options_.launch_configuration && options_.launch_configuration->has_new_profile()) {
      // 隔离分支绝不调用会创建默认目录的函数，也绝不在失败后回落普通数据根。
      if (!options_.launch_configuration->Revalidate(bundle_root)) {
        FailStart(Failure("worker_data_root_unavailable", "nativeWorker.error.dataRoot"));
        return;
      }
      data_root = options_.launch_configuration->profile_root();
    } else {
      data_root = BuildPrivateDataRoot(sid_string);
      if (data_root.empty() || !EnsurePrivateDataRoot(data_root, sid_string,
            reinterpret_cast<PSID>(sid_buffer.data()))) {
        FailStart(Failure("worker_data_root_unavailable", "nativeWorker.error.dataRoot"));
        return;
      }
    }
    if (!IsDisjoint(bundle_root, data_root)) {
      FailStart(Failure("worker_data_root_unavailable", "nativeWorker.error.dataRoot"));
      return;
    }
    if (stop_requested_.load(std::memory_order_acquire)) {
      FailStart(Failure("worker_stopped", "nativeWorker.error.stopped"));
      return;
    }

    const std::wstring worker_executable = JoinPath(JoinPath(bundle_root, L"Worker"), L"Worker.exe");
    const DWORD worker_attributes = GetFileAttributesW(worker_executable.c_str());
    if (worker_attributes == INVALID_FILE_ATTRIBUTES ||
        (worker_attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0 ||
        !CheckPathComponents(worker_executable, true, false)) {
      FailStart(Failure("worker_bundle_unavailable", "nativeWorker.error.bundle"));
      return;
    }

    if (!AcquireSingleton(data_root, sid_string)) {
      FailStart(Failure("worker_already_running", "nativeWorker.error.alreadyRunning"));
      return;
    }

    HANDLE stderr_file = INVALID_HANDLE_VALUE;
    if (!CreateChildDiagnosticFile(data_root, sid_string, &stderr_file)) {
      FailStart(Failure("worker_diagnostics_unavailable", "nativeWorker.error.diagnostics"));
      return;
    }
    ScopedHandle child_stderr(stderr_file);

    SECURITY_ATTRIBUTES pipe_attributes{};
    pipe_attributes.nLength = sizeof(pipe_attributes);
    pipe_attributes.bInheritHandle = TRUE;
    HANDLE child_stdin_raw = INVALID_HANDLE_VALUE;
    HANDLE parent_stdin_raw = INVALID_HANDLE_VALUE;
    HANDLE parent_stdout_raw = INVALID_HANDLE_VALUE;
    HANDLE child_stdout_raw = INVALID_HANDLE_VALUE;
    if (!CreatePipe(&child_stdin_raw, &parent_stdin_raw, &pipe_attributes, 0) ||
        !CreatePipe(&parent_stdout_raw, &child_stdout_raw, &pipe_attributes, 0)) {
      ScopedHandle a(child_stdin_raw), b(parent_stdin_raw), c(parent_stdout_raw), d(child_stdout_raw);
      FailStart(Failure("worker_pipe_unavailable", "nativeWorker.error.pipe"));
      return;
    }
    ScopedHandle child_stdin(child_stdin_raw);
    ScopedHandle parent_stdin(parent_stdin_raw);
    ScopedHandle parent_stdout(parent_stdout_raw);
    ScopedHandle child_stdout(child_stdout_raw);
    if (!SetHandleInformation(parent_stdin.get(), HANDLE_FLAG_INHERIT, 0) ||
        !SetHandleInformation(parent_stdout.get(), HANDLE_FLAG_INHERIT, 0)) {
      FailStart(Failure("worker_pipe_unavailable", "nativeWorker.error.pipe"));
      return;
    }

    SIZE_T attribute_bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attribute_bytes);
    if (attribute_bytes == 0 || attribute_bytes > 64 * 1024) {
      FailStart(Failure("worker_start_failed", "nativeWorker.error.startup"));
      return;
    }
    std::vector<uint8_t> attribute_storage(attribute_bytes);
    auto* attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attribute_storage.data());
    if (!InitializeProcThreadAttributeList(attributes, 1, 0, &attribute_bytes)) {
      FailStart(Failure("worker_start_failed", "nativeWorker.error.startup"));
      return;
    }
    const std::array<HANDLE, 3> inherited_handles = {
        child_stdin.get(), child_stdout.get(), child_stderr.get()};
    const BOOL updated = UpdateProcThreadAttribute(attributes, 0,
        PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        const_cast<HANDLE*>(inherited_handles.data()), sizeof(inherited_handles), nullptr, nullptr);
    if (!updated) {
      DeleteProcThreadAttributeList(attributes);
      FailStart(Failure("worker_start_failed", "nativeWorker.error.startup"));
      return;
    }

    ScopedHandle job(CreateJobObjectW(nullptr, nullptr));
    if (!job.get()) {
      DeleteProcThreadAttributeList(attributes);
      FailStart(Failure("worker_job_unavailable", "nativeWorker.error.job"));
      return;
    }
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION job_limits{};
    job_limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job.get(), JobObjectExtendedLimitInformation,
                                 &job_limits, sizeof(job_limits))) {
      DeleteProcThreadAttributeList(attributes);
      FailStart(Failure("worker_job_unavailable", "nativeWorker.error.job"));
      return;
    }

    std::wstring command = QuoteWindowsArgument(worker_executable) +
        L" --desktop --resource-root " + QuoteWindowsArgument(bundle_root) +
        L" --data-root " + QuoteWindowsArgument(data_root);
    if (command.size() >= 32767) {
      DeleteProcThreadAttributeList(attributes);
      FailStart(Failure("worker_start_failed", "nativeWorker.error.startup"));
      return;
    }
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = child_stdin.get();
    startup.StartupInfo.hStdOutput = child_stdout.get();
    startup.StartupInfo.hStdError = child_stderr.get();
    startup.lpAttributeList = attributes;
    PROCESS_INFORMATION process_info{};
    const DWORD flags = CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED;
    const BOOL created = CreateProcessW(worker_executable.c_str(), command.data(), nullptr,
        nullptr, TRUE, flags, nullptr, bundle_root.c_str(), &startup.StartupInfo, &process_info);
    DeleteProcThreadAttributeList(attributes);
    if (!created) {
      FailStart(Failure("worker_start_failed", "nativeWorker.error.startup"));
      return;
    }
    ScopedHandle process(process_info.hProcess);
    ScopedHandle primary_thread(process_info.hThread);

    if (!AssignProcessToJobObject(job.get(), process.get())) {
      // This process was created by this supervisor but could not be placed into
      // our kill-on-close job (including an incompatible nested parent job).
      TerminateProcess(process.get(), ERROR_ACCESS_DENIED);
      WaitForSingleObject(process.get(), INFINITE);
      FailStart(Failure("worker_job_unavailable", "nativeWorker.error.job"));
      return;
    }

    {
      std::lock_guard<std::mutex> lock(handles_mutex_);
      process_handle_ = process.release();
      created_worker_pid_ = process_info.dwProcessId;
      startup_reap_observation_ = OwnedWorkerProcessObservation{};
      job_handle_ = job.release();
      input_write_ = parent_stdin.release();
      output_read_ = parent_stdout.release();
    }
    child_stdin.reset();
    child_stdout.reset();
    child_stderr.reset();
    // 未绑定本次原始对象的 PID/创建时间/映像 duplicate 前，不允许 Worker 进入 ready/媒体服务。
    if (!InitializeOwnedProcessWitness(process_info.dwProcessId, worker_executable)) {
      FailStart(Failure("worker_identity_unavailable", "nativeWorker.error.startup"));
      return;
    }

    if (stop_requested_.load(std::memory_order_acquire) || ResumeThread(primary_thread.get()) == static_cast<DWORD>(-1)) {
      CloseOwnedJob();
      FailStart(Failure("worker_start_failed", "nativeWorker.error.startup"));
      return;
    }

    HANDLE process_handle = GetProcessHandle();
    const DWORD expected_pid = GetProcessId(process_handle);
    std::string ready_line;
    bool eof = false;
    const bool got_line = ReadProtocolLine(GetOutputHandle(), process_handle,
        options_.startup_timeout_ms, stop_requested_, [this] { CloseOwnedJob(); },
        &pipe_buffer_, &ready_line, &eof);
    WorkerReady ready;
    std::string capability;
    const bool parsed_ready = got_line && !eof &&
        ParseReady(ready_line, expected_pid, &ready, &capability);
    if (!ready_line.empty()) SecureZeroMemory(ready_line.data(), ready_line.size());
    if (!parsed_ready) {
      SecureZeroMemory(capability.data(), capability.size());
      CloseOwnedJob();
      FailStart(Failure("worker_ready_invalid", "nativeWorker.error.ready"));
      return;
    }
    if (stop_requested_.load(std::memory_order_acquire)) {
      SecureZeroMemory(capability.data(), capability.size());
      CloseOwnedJob();
      FailStart(Failure("worker_stopped", "nativeWorker.error.stopped"));
      return;
    }

    std::vector<ReadyCallback> callbacks;
    bool startup_was_cancelled = false;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      startup_was_cancelled = state_ != State::kStarting || stopping_;
      if (!startup_was_cancelled) {
        ready_ = ready;
        capability_ = std::move(capability);
        ready_ever_published_.store(true, std::memory_order_release);
        state_ = State::kRunning;
        callbacks.swap(ready_callbacks_);
      }
    }
    if (startup_was_cancelled) {
      if (!capability.empty()) SecureZeroMemory(capability.data(), capability.size());
      CloseInputPipe();
      CloseOwnedJob();
      HANDLE canceled_process = GetProcessHandle();
      if (IsValidHandle(canceled_process)) WaitForSingleObject(canceled_process, INFINITE);
      CloseOutputPipe();
      CloseProcessAndMutex();
      return;
    }
    try {
      reader_thread_ = std::thread([this] { ReaderLoop(); });
      writer_thread_ = std::thread([this] { WriterLoop(); });
      timer_thread_ = std::thread([this] { TimerLoop(); });
    } catch (...) {
      FailSession(Failure("worker_start_failed", "nativeWorker.error.startup"), true);
      for (auto& callback : callbacks) DispatchReady(std::move(callback), false, {},
          Failure("worker_start_failed", "nativeWorker.error.startup"));
      return;
    }
    for (auto& callback : callbacks) DispatchReady(std::move(callback), true, ready, {});
  }

  bool AcquireSingleton(const std::wstring& data_root,
                        const std::wstring& sid) {
    const std::wstring mutex_name = L"Global\\ChaSteady.Worker." + sid + L"." + Hex64(HashPath(data_root));
    const std::wstring sddl = L"D:P(A;;GA;;;" + sid + L")(A;;GA;;;SY)(A;;GA;;;BA)";
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                                                               &descriptor, nullptr)) return false;
    SECURITY_ATTRIBUTES attributes{};
    attributes.nLength = sizeof(attributes);
    attributes.lpSecurityDescriptor = descriptor;
    attributes.bInheritHandle = FALSE;
    SetLastError(ERROR_SUCCESS);
    HANDLE mutex = CreateMutexW(&attributes, TRUE, mutex_name.c_str());
    const DWORD error = GetLastError();
    LocalFree(descriptor);
    if (!IsValidHandle(mutex)) return false;
    if (error == ERROR_ALREADY_EXISTS) {
      CloseHandle(mutex);
      return false;
    }
    {
      std::lock_guard<std::mutex> lock(handles_mutex_);
      singleton_mutex_ = mutex;
    }
    return true;
  }

  void RecordReapedStartupFailure(HANDLE original, DWORD actual_wait) {
    if (actual_wait != WAIT_OBJECT_0 || ready_ever_published_.load(std::memory_order_acquire)) return;
    std::lock_guard<std::mutex> lock(handles_mutex_);
    if (!IsValidHandle(original) || original != process_handle_ || process_witness_ ||
        process_generation_ == 0 || created_worker_pid_ == 0) return;
    // 原始 handle 仍持有且真实等待成功；此独立证据不伪造完整身份或 lease 终态。
    startup_reap_observation_ = OwnedWorkerProcessObservation{};
    startup_reap_observation_.generation = process_generation_;
    startup_reap_observation_.pid = created_worker_pid_;
    startup_reap_observation_.original_handle_observed = true;
    startup_reap_observation_.wait_state = OwnedWorkerProcessObservation::WaitState::kSignaled;
    startup_reap_observation_.startup_failure_reaped = true;
  }

  void FailStart(WorkerFailure failure) {
    std::vector<ReadyCallback> callbacks;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (state_ == State::kStopped && !ready_callbacks_.empty()) {
        // A concurrent Stop already began. Complete its callbacks below.
      }
      state_ = State::kStopped;
      stopping_ = true;
      terminal_failure_ = failure;
      callbacks.swap(ready_callbacks_);
      condition_.notify_all();
    }
    CloseInputPipe();
    CloseOwnedJob();
    HANDLE process = GetProcessHandle();
    if (IsValidHandle(process)) {
      const DWORD actual_wait = WaitForSingleObject(process, INFINITE);
      RecordReapedStartupFailure(process, actual_wait);
    }
    CloseOutputPipe();
    CloseProcessAndMutex();
    for (auto& callback : callbacks) DispatchReady(std::move(callback), false, {}, failure);
  }

  void QueueRequest(Action action, const std::string& argument, ReplyCallback callback,
                    bool internal_release = false) {
    if (!callback && !internal_release) return;
    WorkerFailure failure;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (state_ != State::kRunning || shutdown_queued_) {
        failure = Failure(state_ == State::kShuttingDown ? "worker_shutting_down" : "worker_not_ready",
            state_ == State::kShuttingDown ? "nativeWorker.error.stopping" : "nativeWorker.error.notReady");
      } else if (pending_.size() >= 64) {
        failure = Failure("worker_request_limit", "nativeWorker.error.requestLimit");
      } else {
        const uint64_t id = next_request_id_++;
        const std::string request_id = "native-" + std::to_string(id);
        const char* action_name = nullptr;
        const char* extra_key = nullptr;
        switch (action) {
          case Action::kWebSession: action_name = "web_session"; break;
          case Action::kAcquireMedia: action_name = "acquire_media"; extra_key = "artifact_id"; break;
          case Action::kReleaseMedia: action_name = "release_media"; extra_key = "lease_id"; break;
          case Action::kShutdown: action_name = "shutdown"; break;
        }
        Outbound outbound{action, request_id,
            NewRequestJson(id, capability_, action_name, extra_key,
                           extra_key == nullptr ? std::string() : argument)};
        pending_.emplace(request_id, Pending{action, std::move(callback),
            std::chrono::steady_clock::now() + std::chrono::milliseconds(options_.request_timeout_ms)});
        outbound_.push_back(std::move(outbound));
        if (action == Action::kShutdown) {
          shutdown_queued_ = true;
          state_ = State::kShuttingDown;
        }
        condition_.notify_all();
        return;
      }
    }
    if (callback) DispatchReply(std::move(callback), ErrorReply(std::move(failure)));
  }

  void ReaderLoop() {
    for (;;) {
      if (stop_requested_.load(std::memory_order_acquire)) return;
      std::string line;
      bool eof = false;
      HANDLE process = GetProcessHandle();
      if (!ReadProtocolLine(GetOutputHandle(), process, INFINITE, stop_requested_,
                            [this] { CloseOwnedJob(); }, &pipe_buffer_, &line, &eof)) {
        if (!stop_requested_.load(std::memory_order_acquire)) {
          FailSession(Failure("worker_pipe_read_failed", "nativeWorker.error.protocol"), true);
        }
        return;
      }
      if (eof) {
        if (stop_requested_.load(std::memory_order_acquire)) return;
        stdout_eof_observed_.store(true, std::memory_order_release);
        const bool shutdown_acknowledged = shutdown_acknowledged_.load(std::memory_order_acquire);
        if (IsValidHandle(process) && WaitForSingleObject(process, 0) != WAIT_OBJECT_0 &&
            !shutdown_acknowledged) {
          // An unsolicited stdout EOF is fatal. Stop only the process tree this
          // supervisor created, then wait for the owned process to actually exit.
          CloseOwnedJob();
        }
        DWORD process_wait = WAIT_TIMEOUT;
        while (IsValidHandle(process) &&
               !stop_requested_.load(std::memory_order_acquire)) {
          process_wait = WaitForSingleObject(process, 100);
          if (process_wait == WAIT_OBJECT_0 || process_wait == WAIT_FAILED) break;
        }
        if (stop_requested_.load(std::memory_order_acquire)) return;
        if (IsValidHandle(process) && process_wait != WAIT_OBJECT_0) {
          FailSession(Failure("worker_exit_wait_failed", "nativeWorker.error.exited"), true);
          return;
        }
        DWORD exit_code = 0;
        if (IsValidHandle(process) && GetExitCodeProcess(process, &exit_code) && exit_code != 0) {
          shutdown_fallback_requested_.store(true, std::memory_order_release);
        }
        FailSession(Failure("worker_exited", "nativeWorker.error.exited"), true);
        return;
      }
      if (!HandleResponseLine(line)) {
        FailSession(Failure("worker_protocol_invalid", "nativeWorker.error.protocol"), true);
        return;
      }
    }
  }

  bool HandleResponseLine(const std::string& line) {
    JsonValue root;
    JsonParser parser(line);
    if (!parser.Parse(&root) || root.type != JsonValue::Type::kObject) return false;
    const JsonValue* protocol_value = Member(root, "protocol");
    const JsonValue* request_id_value = Member(root, "request_id");
    const JsonValue* ok_value = Member(root, "ok");
    uint64_t protocol = 0;
    std::string request_id;
    bool ok = false;
    if (!JsonUnsigned(protocol_value, &protocol) || protocol != 1 ||
        !JsonString(request_id_value, &request_id) || !IsAsciiToken(request_id, 1, 128) ||
        !JsonBoolean(ok_value, &ok)) return false;

    Action action;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      const auto pending = pending_.find(request_id);
      if (pending == pending_.end()) return false;
      action = pending->second.action;
    }
    WorkerReply reply;
    reply.ok = ok;
    if (ok) {
      if (!HasExactKeys(root, {"protocol", "request_id", "ok", "result"}) ||
          !ParseSuccessResult(action, root, &reply)) return false;
    } else {
      if (!HasExactKeys(root, {"protocol", "request_id", "ok", "error"}) ||
          !ParseErrorEnvelope(root, &reply.failure)) return false;
    }

    bool release_after_duplication_failure = false;
    std::string acquired_lease;
    if (action == Action::kAcquireMedia && ok) {
      const uint64_t remote = reply.remote_worker_handle;
      HANDLE duplicated = INVALID_HANDLE_VALUE;
      HANDLE process = GetProcessHandle();
      if (remote == 0 || remote > static_cast<uint64_t>(std::numeric_limits<uintptr_t>::max()) ||
          !IsValidHandle(process) ||
          !DuplicateHandle(process, reinterpret_cast<HANDLE>(static_cast<uintptr_t>(remote)),
                           GetCurrentProcess(), &duplicated, 0, FALSE, DUPLICATE_SAME_ACCESS)) {
        acquired_lease = reply.lease_id;
        reply = ErrorReply("media_handle_duplication_failed", "nativeMedia.error.leaseUnavailable");
        release_after_duplication_failure = true;
      } else {
        reply.owned_read_handle = OwnedWorkerHandle(duplicated);
      }
    }

    ReplyCallback callback;
    bool await_process_exit = false;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      const auto pending = pending_.find(request_id);
      if (pending == pending_.end()) return true;  // A timeout already completed it.
      callback = std::move(pending->second.callback);
      pending_.erase(pending);
      if (action == Action::kShutdown) {
        if (ok && reply.shutting_down) {
          shutdown_acknowledged_.store(true, std::memory_order_release);
          shutdown_fallback_requested_.store(false, std::memory_order_release);
          shutdown_deadline_ = std::chrono::steady_clock::now() +
              std::chrono::milliseconds(options_.graceful_shutdown_timeout_ms);
          shutdown_callback_ = std::move(callback);
          await_process_exit = true;
        } else if (!ok && state_ == State::kShuttingDown) {
          shutdown_queued_ = false;
          state_ = State::kRunning;
        }
      }
      condition_.notify_all();
    }
    if (action == Action::kShutdown && ok && reply.shutting_down) CloseInputPipe();
    if (release_after_duplication_failure) {
      QueueRequest(Action::kReleaseMedia, acquired_lease, {}, true);
    }
    if (!await_process_exit && callback) {
      try { callback(std::move(reply)); } catch (...) {}
    }
    return true;
  }

  bool ParseSuccessResult(Action action, const JsonValue& root, WorkerReply* reply) {
    const JsonValue* result = Member(root, "result");
    if (result == nullptr || result->type != JsonValue::Type::kObject) return false;
    switch (action) {
      case Action::kWebSession:
        return HasExactKeys(*result, {"url"}) && JsonString(Member(*result, "url"), &reply->url) &&
               reply->url.size() <= 4096 && !reply->url.empty();
      case Action::kAcquireMedia: {
        uint64_t handle = 0;
        uint64_t width = 0;
        uint64_t height = 0;
        if (!HasExactKeys(*result, {"lease_id", "handle", "width", "height", "audio_present"}) ||
            !JsonString(Member(*result, "lease_id"), &reply->lease_id) ||
            !IsCanonicalUuid(reply->lease_id) ||
            !JsonUnsigned(Member(*result, "handle"), &handle) || handle == 0 ||
            !JsonUnsigned(Member(*result, "width"), &width) || width < 2 || width > 8192 || (width & 1) != 0 ||
            !JsonUnsigned(Member(*result, "height"), &height) || height < 2 || height > 8192 || (height & 1) != 0 ||
            !JsonBoolean(Member(*result, "audio_present"), &reply->audio_present)) return false;
        reply->remote_worker_handle = handle;
        reply->width = static_cast<int>(width);
        reply->height = static_cast<int>(height);
        return true;
      }
      case Action::kReleaseMedia:
        return HasExactKeys(*result, {"released"}) &&
               JsonBoolean(Member(*result, "released"), &reply->released);
      case Action::kShutdown:
        return HasExactKeys(*result, {"shutting_down"}) &&
               JsonBoolean(Member(*result, "shutting_down"), &reply->shutting_down) &&
               reply->shutting_down;
    }
    return false;
  }

  void WriterLoop() {
    for (;;) {
      Outbound outbound;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        condition_.wait(lock, [this] { return stopping_ || !outbound_.empty(); });
        if (stopping_) return;
        outbound = std::move(outbound_.front());
        outbound_.pop_front();
      }
      HANDLE pipe = GetInputHandle();
      if (!IsValidHandle(pipe)) {
        if (!outbound.line.empty()) SecureZeroMemory(outbound.line.data(), outbound.line.size());
        FailSession(Failure("worker_pipe_closed", "nativeWorker.error.protocol"), true);
        return;
      }
      size_t offset = 0;
      bool write_ok = true;
      while (offset < outbound.line.size()) {
        const DWORD count = static_cast<DWORD>(std::min<size_t>(outbound.line.size() - offset, 65536));
        DWORD written = 0;
        if (!WriteFile(pipe, outbound.line.data() + offset, count, &written, nullptr) || written == 0) {
          write_ok = false;
          break;
        }
        offset += written;
      }
      if (!write_ok) {
        if (!outbound.line.empty()) SecureZeroMemory(outbound.line.data(), outbound.line.size());
        if (!stop_requested_.load(std::memory_order_acquire)) {
          FailSession(Failure("worker_pipe_write_failed", "nativeWorker.error.protocol"), true);
        }
        return;
      }
      if (!outbound.line.empty()) SecureZeroMemory(outbound.line.data(), outbound.line.size());
      if (outbound.action == Action::kShutdown) CloseInputPipe();
    }
  }

  void TimerLoop() {
    for (;;) {
      std::vector<ReplyCallback> expired;
      bool force_shutdown = false;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        if (stopping_) return;
        auto nearest = std::chrono::steady_clock::time_point::max();
        for (const auto& item : pending_) nearest = std::min(nearest, item.second.deadline);
        const bool awaiting_exit = shutdown_callback_ &&
            shutdown_acknowledged_.load(std::memory_order_acquire) &&
            !shutdown_fallback_requested_.load(std::memory_order_acquire);
        if (awaiting_exit) nearest = std::min(nearest, shutdown_deadline_);
        if (nearest == std::chrono::steady_clock::time_point::max()) {
          condition_.wait(lock, [this] {
            return stopping_ || !pending_.empty() ||
                (shutdown_callback_ && shutdown_acknowledged_.load(std::memory_order_acquire) &&
                 !shutdown_fallback_requested_.load(std::memory_order_acquire));
          });
          if (stopping_) return;
          continue;
        }
        condition_.wait_until(lock, nearest);
        if (stopping_) return;
        const auto now = std::chrono::steady_clock::now();
        for (auto it = pending_.begin(); it != pending_.end();) {
          if (it->second.deadline <= now) {
            expired.push_back(std::move(it->second.callback));
            it = pending_.erase(it);
          } else {
            ++it;
          }
        }
        if (shutdown_callback_ && shutdown_acknowledged_.load(std::memory_order_acquire) &&
            !shutdown_fallback_requested_.load(std::memory_order_acquire) &&
            shutdown_deadline_ <= now) {
          shutdown_fallback_requested_.store(true, std::memory_order_release);
          force_shutdown = true;
        }
      }
      if (!expired.empty()) {
        const WorkerFailure failure = Failure("worker_request_timeout", "nativeWorker.error.timeout");
        for (auto& callback : expired) {
          if (callback) DispatchReply(std::move(callback), ErrorReply(failure));
        }
        FailSession(failure, true);
        return;
      }
      if (force_shutdown) {
        // Grace expired after the worker acknowledged shutdown. Kill only the
        // job created for this Worker.exe tree; ReaderLoop will still wait for
        // stdout EOF and the actual process signal before completing shutdown.
        CloseOwnedJob();
      }
    }
  }

  void FailSession(WorkerFailure failure, bool notify_exit) {
    std::vector<ReplyCallback> callbacks;
    std::vector<ReadyCallback> ready_callbacks;
    ReplyCallback shutdown_callback;
    ExitCallback exit_callback;
    bool was_started = false;
    const OwnedWorkerProcessObservation observation = ObserveOwnedProcess();
    // 会话失败通知不是终态；正常 shutdown 仍须 ACK、真实 stdout EOF 和原对象 signaled。
    const bool process_completed = failure.code == "worker_exited" &&
        shutdown_acknowledged_.load(std::memory_order_acquire) &&
        stdout_eof_observed_.load(std::memory_order_acquire) && observation.IsVerifiedTerminal();
    const bool forced_shutdown = shutdown_fallback_requested_.load(std::memory_order_acquire) ||
        observation.forced_cleanup_requested || (process_completed && !observation.IsGracefulTerminal());
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (state_ == State::kStopped || stopping_) return;
      was_started = state_ == State::kRunning || state_ == State::kShuttingDown;
      state_ = State::kStopped;
      stopping_ = true;
      terminal_failure_ = failure;
      for (auto& item : pending_) callbacks.push_back(std::move(item.second.callback));
      pending_.clear();
      for (auto& item : outbound_) {
        if (!item.line.empty()) SecureZeroMemory(item.line.data(), item.line.size());
      }
      outbound_.clear();
      shutdown_callback = std::move(shutdown_callback_);
      ready_callbacks.swap(ready_callbacks_);
      if (notify_exit && was_started) exit_callback = exit_callback_;
      condition_.notify_all();
    }
    stop_requested_.store(true, std::memory_order_release);
    CloseInputPipe();
    CloseOwnedJob();
    for (auto& callback : callbacks) {
      if (callback) DispatchReply(std::move(callback), ErrorReply(failure));
    }
    for (auto& callback : ready_callbacks) DispatchReady(std::move(callback), false, {}, failure);
    if (shutdown_callback) {
      WorkerReply reply;
      if (process_completed) {
        reply.ok = true;
        reply.shutting_down = true;
        reply.shutdown_timed_out = forced_shutdown;
      } else {
        reply = ErrorReply(failure);
      }
      try { shutdown_callback(std::move(reply)); } catch (...) {}
    }
    if (exit_callback) {
      try { exit_callback(); } catch (...) {}
    }
  }

  void CloseInputPipe() {
    std::lock_guard<std::mutex> lock(handles_mutex_);
    CloseHandleIfValid(input_write_);
    input_write_ = INVALID_HANDLE_VALUE;
  }

  void CloseOutputPipe() {
    std::lock_guard<std::mutex> lock(handles_mutex_);
    CloseHandleIfValid(output_read_);
    output_read_ = INVALID_HANDLE_VALUE;
  }

  static void CloseTransferredJob(HANDLE job, const std::shared_ptr<OwnedProcessWitness>& witness,
                                  const std::shared_ptr<std::atomic<bool>>& forced_cleanup) {
    if (!IsValidHandle(job)) return;
    // 记录请求而非伪造终态；CloseHandle 失败或进程仍 live 都不能授权清账。
    if (!witness || !IsValidHandle(witness->process.get()) ||
        WaitForSingleObject(witness->process.get(), 0) != WAIT_OBJECT_0) {
      forced_cleanup->store(true, std::memory_order_release);
    }
    CloseHandle(job);
  }

  void CloseOwnedJob() {
    std::lock_guard<std::mutex> lock(handles_mutex_);
    CloseTransferredJob(job_handle_, process_witness_, forced_cleanup_requested_);
    job_handle_ = INVALID_HANDLE_VALUE;
  }

  void CloseProcessAndMutex() {
    std::lock_guard<std::mutex> lock(handles_mutex_);
    CloseHandleIfValid(process_handle_);
    process_handle_ = INVALID_HANDLE_VALUE;
    CloseHandleIfValid(singleton_mutex_);
    singleton_mutex_ = INVALID_HANDLE_VALUE;
  }

  static void CloseHandleIfValid(HANDLE handle) {
    if (IsValidHandle(handle)) CloseHandle(handle);
  }

  HANDLE GetProcessHandle() const {
    std::lock_guard<std::mutex> lock(handles_mutex_);
    return process_handle_;
  }

  HANDLE GetInputHandle() const {
    std::lock_guard<std::mutex> lock(handles_mutex_);
    return input_write_;
  }

  HANDLE GetOutputHandle() const {
    std::lock_guard<std::mutex> lock(handles_mutex_);
    return output_read_;
  }

  void CancelAndJoinIoThreads() {
    auto cancel = [](std::thread& thread) {
      if (thread.joinable() && thread.get_id() != std::this_thread::get_id()) {
        CancelSynchronousIo(thread.native_handle());
      }
    };
    cancel(reader_thread_);
    cancel(writer_thread_);
    cancel(timer_thread_);
    JoinThread(reader_thread_);
    JoinThread(writer_thread_);
    JoinThread(timer_thread_);
  }

  static void JoinThread(std::thread& thread) {
    if (!thread.joinable()) return;
    if (thread.get_id() == std::this_thread::get_id()) {
      thread.detach();
    } else {
      thread.join();
    }
  }

  const WorkerSupervisorOptions options_;
  mutable std::mutex mutex_;
  std::condition_variable condition_;
  State state_ = State::kNew;
  bool stopping_ = false;
  bool shutdown_queued_ = false;
  std::atomic<bool> shutdown_acknowledged_{false};
  std::atomic<bool> shutdown_fallback_requested_{false};
  std::atomic<bool> stdout_eof_observed_{false};
  std::atomic<bool> ready_ever_published_{false};
  ReplyCallback shutdown_callback_;
  std::chrono::steady_clock::time_point shutdown_deadline_{};
  uint64_t next_request_id_ = 1;
  std::string capability_;
  WorkerReady ready_;
  WorkerFailure terminal_failure_;
  std::map<std::string, Pending> pending_;
  std::deque<Outbound> outbound_;
  std::vector<ReadyCallback> ready_callbacks_;
  ExitCallback exit_callback_;

  mutable std::mutex handles_mutex_;
  std::shared_ptr<OwnedProcessWitness> process_witness_;
  uint64_t process_generation_ = 0;
  DWORD created_worker_pid_ = 0;
  OwnedWorkerProcessObservation startup_reap_observation_;
  const std::shared_ptr<std::atomic<bool>> forced_cleanup_requested_ =
      std::make_shared<std::atomic<bool>>(false);
  HANDLE process_handle_ = INVALID_HANDLE_VALUE;
  HANDLE job_handle_ = INVALID_HANDLE_VALUE;
  HANDLE input_write_ = INVALID_HANDLE_VALUE;
  HANDLE output_read_ = INVALID_HANDLE_VALUE;
  HANDLE singleton_mutex_ = INVALID_HANDLE_VALUE;
  std::string pipe_buffer_;
  std::atomic<bool> stop_requested_{false};
  std::atomic<bool> stop_called_{false};
  std::thread startup_thread_;
  std::thread reader_thread_;
  std::thread writer_thread_;
  std::thread timer_thread_;
};

WorkerSupervisor::WorkerSupervisor(WorkerSupervisorOptions options)
    : impl_(std::make_unique<Impl>(options)) {}
WorkerSupervisor::~WorkerSupervisor() = default;
void WorkerSupervisor::StartAsync(ReadyCallback callback) { impl_->StartAsync(std::move(callback)); }
void WorkerSupervisor::GetWebSession(ReplyCallback callback) { impl_->GetWebSession(std::move(callback)); }
void WorkerSupervisor::AcquireMedia(const std::string& artifact_id, ReplyCallback callback) {
  impl_->AcquireMedia(artifact_id, std::move(callback));
}
void WorkerSupervisor::ReleaseMedia(const std::string& lease_id, ReplyCallback callback) {
  impl_->ReleaseMedia(lease_id, std::move(callback));
}
void WorkerSupervisor::RequestShutdown(ReplyCallback callback) { impl_->RequestShutdown(std::move(callback)); }
void WorkerSupervisor::SetExitCallback(ExitCallback callback) { impl_->SetExitCallback(std::move(callback)); }
OwnedWorkerProcessObservation WorkerSupervisor::ObserveOwnedProcess() const { return impl_->ObserveOwnedProcess(); }
bool WorkerSupervisor::IsReady() const noexcept { return impl_->IsReady(); }
void WorkerSupervisor::Stop() { impl_->Stop(); }

}  // namespace chasteady
