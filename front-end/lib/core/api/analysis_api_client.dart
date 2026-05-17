import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;

import '../models/analysis_result.dart';

class AnalysisApiClient {
  const AnalysisApiClient({this.baseUrl = 'http://127.0.0.1:8000'});

  final String baseUrl;

  Future<AnalysisResult> analyzeVideo(PlatformFile file) async {
    final bytes = file.bytes;
    if (bytes == null) {
      throw StateError('Selected file does not contain bytes. Pick the file again.');
    }

    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$baseUrl/analyze'),
    );
    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: file.name,
      ),
    );

    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }

    return AnalysisResult.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }
}
