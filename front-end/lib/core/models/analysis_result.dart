class AnalysisResult {
  const AnalysisResult({
    required this.videoName,
    required this.durationSeconds,
    required this.attacks,
    required this.successfulThrows,
    required this.failedThrows,
    required this.annotatedVideoPath,
    this.annotatedVideoUrl,
    required this.reportPath,
    this.reportUrl,
    required this.events,
  });

  final String videoName;
  final double durationSeconds;
  final int attacks;
  final int successfulThrows;
  final int failedThrows;
  final String annotatedVideoPath;
  final String? annotatedVideoUrl;
  final String reportPath;
  final String? reportUrl;
  final List<AnalysisEvent> events;

  factory AnalysisResult.fromJson(Map<String, dynamic> json) {
    return AnalysisResult(
      videoName: json['videoName'] as String,
      durationSeconds: (json['durationSeconds'] as num).toDouble(),
      attacks: json['attacks'] as int,
      successfulThrows: json['successfulThrows'] as int,
      failedThrows: json['failedThrows'] as int,
      annotatedVideoPath: json['annotatedVideoPath'] as String,
      annotatedVideoUrl: json['annotatedVideoUrl'] as String?,
      reportPath: json['reportPath'] as String,
      reportUrl: json['reportUrl'] as String?,
      events: (json['events'] as List<dynamic>)
          .map((event) => AnalysisEvent.fromJson(event as Map<String, dynamic>))
          .toList(),
    );
  }
}

class AnalysisEvent {
  const AnalysisEvent({
    required this.timeSeconds,
    required this.result,
    required this.description,
  });

  final double timeSeconds;
  final String result;
  final String description;

  factory AnalysisEvent.fromJson(Map<String, dynamic> json) {
    return AnalysisEvent(
      timeSeconds: (json['timeSeconds'] as num).toDouble(),
      result: json['result'] as String,
      description: json['description'] as String,
    );
  }
}
