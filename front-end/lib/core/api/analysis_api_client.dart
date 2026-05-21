import 'dart:async';
import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;

import '../models/analysis_progress.dart';
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

  Stream<AnalysisStreamEvent> analyzeVideoStream(PlatformFile file) async* {
    final bytes = file.bytes;
    if (bytes == null) {
      throw StateError('Selected file does not contain bytes. Pick the file again.');
    }

    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$baseUrl/analyze/stream'),
    );
    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: file.name,
      ),
    );

    final streamedResponse = await request.send();
    if (streamedResponse.statusCode < 200 || streamedResponse.statusCode >= 300) {
      final body = await streamedResponse.stream.bytesToString();
      throw Exception('Backend error ${streamedResponse.statusCode}: $body');
    }

    var buffer = '';
    await for (final chunk in streamedResponse.stream.transform(utf8.decoder)) {
      buffer += chunk;
      final lines = buffer.split('\n');
      buffer = lines.removeLast();
      for (final line in lines) {
        if (line.trim().isEmpty) {
          continue;
        }
        final json = jsonDecode(line) as Map<String, dynamic>;
        final type = json['type'] as String?;
        if (type == 'progress') {
          yield AnalysisStreamEvent.progress(AnalysisProgress.fromJson(json));
        } else if (type == 'result') {
          final data = json['data'] as Map<String, dynamic>;
          yield AnalysisStreamEvent.result(AnalysisResult.fromJson(data));
        } else if (type == 'error') {
          throw Exception(json['message'] as String? ?? 'Analysis failed');
        }
      }
    }

    if (buffer.trim().isNotEmpty) {
      final json = jsonDecode(buffer) as Map<String, dynamic>;
      final type = json['type'] as String?;
      if (type == 'progress') {
        yield AnalysisStreamEvent.progress(AnalysisProgress.fromJson(json));
      } else if (type == 'result') {
        final data = json['data'] as Map<String, dynamic>;
        yield AnalysisStreamEvent.result(AnalysisResult.fromJson(data));
      } else if (type == 'error') {
        throw Exception(json['message'] as String? ?? 'Analysis failed');
      }
    }
  }
}

class AnalysisStreamEvent {
  const AnalysisStreamEvent._({this.progress, this.result});

  factory AnalysisStreamEvent.progress(AnalysisProgress progress) {
    return AnalysisStreamEvent._(progress: progress);
  }

  factory AnalysisStreamEvent.result(AnalysisResult result) {
    return AnalysisStreamEvent._(result: result);
  }

  final AnalysisProgress? progress;
  final AnalysisResult? result;
}
