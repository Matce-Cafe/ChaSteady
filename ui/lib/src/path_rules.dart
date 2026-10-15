/// Accepts local absolute paths only; network URLs and relative paths are rejected.
bool isLocalAbsolutePath(String value) {
  final path = value.trim();
  if (path.isEmpty) return false;
  if (RegExp(r'^[A-Za-z]:[\\/]').hasMatch(path)) return true;
  if (path.startsWith(r'\\')) return true;
  if (path.startsWith('//')) return false;
  return path.startsWith('/');
}
