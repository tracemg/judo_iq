import 'dart:typed_data';

import 'blob_video_url_stub.dart'
    if (dart.library.html) 'blob_video_url_web.dart' as blob_impl;

String mimeTypeForVideo(String fileName) {
  final ext = fileName.contains('.') ? fileName.split('.').last.toLowerCase() : '';
  switch (ext) {
    case 'mov':
      return 'video/quicktime';
    case 'webm':
      return 'video/webm';
    case 'avi':
      return 'video/x-msvideo';
    default:
      return 'video/mp4';
  }
}

String? blobUrlFromBytes(Uint8List bytes, String fileName) {
  return blob_impl.createBlobVideoUrl(bytes, mimeTypeForVideo(fileName));
}

void revokeBlobVideoUrl(String url) {
  blob_impl.revokeBlobVideoUrl(url);
}
