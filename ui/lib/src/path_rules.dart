/// 仅接受本机绝对路径，拒绝 URL、相对路径与浏览器占位 fakepath。
bool isLocalAbsolutePath(String value) {
  final path = value.trim();
  if (path.isEmpty ||
      path.contains('\u0000') ||
      RegExp(
        r'^[A-Za-z]:[\\/]fakepath[\\/]',
        caseSensitive: false,
      ).hasMatch(path))
    return false;
  if (RegExp(r'^[A-Za-z]:[\\/]').hasMatch(path)) return true;
  if (path.startsWith(r'\\')) return true;
  if (path.startsWith('//')) return false;
  return path.startsWith('/');
}
