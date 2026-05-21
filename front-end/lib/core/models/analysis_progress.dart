class AnalysisProgress {
  const AnalysisProgress({
    required this.phase,
    required this.percent,
    this.currentFrame,
    this.totalFrames,
    this.timeSeconds,
  });

  final String phase;
  final double percent;
  final int? currentFrame;
  final int? totalFrames;
  final double? timeSeconds;

  factory AnalysisProgress.fromJson(Map<String, dynamic> json) {
    return AnalysisProgress(
      phase: json['phase'] as String? ?? 'processing',
      percent: (json['percent'] as num?)?.toDouble() ?? 0,
      currentFrame: json['currentFrame'] as int?,
      totalFrames: json['totalFrames'] as int?,
      timeSeconds: (json['timeSeconds'] as num?)?.toDouble(),
    );
  }

  String get phaseLabel {
    switch (phase) {
      case 'upload':
        return 'Wgrywanie klipu';
      case 'loading_model':
        return 'Ladowanie modelu';
      case 'starting':
        return 'Przygotowanie analizy';
      case 'processing':
        return 'Analiza klatek';
      case 'finalizing':
        return 'Zapis wideo i raportu';
      case 'done':
        return 'Zakonczono';
      default:
        return 'Analiza w toku';
    }
  }
}
