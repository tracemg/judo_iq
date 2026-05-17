import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:video_player/video_player.dart';

import '../../core/api/analysis_api_client.dart';
import '../../core/models/analysis_result.dart';

const _backendBaseUrl = 'http://127.0.0.1:8000';

class AnalysisPage extends StatefulWidget {
  const AnalysisPage({super.key});

  @override
  State<AnalysisPage> createState() => _AnalysisPageState();
}

class _AnalysisPageState extends State<AnalysisPage> {
  PlatformFile? _selectedClip;
  AnalysisResult? _result;
  bool _isAnalyzing = false;
  String? _errorMessage;
  final AnalysisApiClient _apiClient = const AnalysisApiClient();

  Future<void> _pickClip() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.video,
      allowMultiple: false,
      withData: true,
    );

    if (result == null || result.files.isEmpty) {
      return;
    }

    setState(() {
      _selectedClip = result.files.single;
      _result = null;
      _errorMessage = null;
    });
  }

  Future<void> _runAnalysis() async {
    final clip = _selectedClip;
    if (clip == null || _isAnalyzing) {
      return;
    }

    setState(() {
      _isAnalyzing = true;
      _errorMessage = null;
    });

    try {
      final analysisResult = await _apiClient.analyzeVideo(clip);
      setState(() {
        _result = analysisResult;
      });
    } catch (error) {
      setState(() {
        _errorMessage = error.toString();
      });
    } finally {
      setState(() {
        _isAnalyzing = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('JudoIQ Analytics'),
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF182230),
        surfaceTintColor: Colors.white,
      ),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final isWide = constraints.maxWidth >= 1000;
            final content = [
              Expanded(
                flex: 5,
                child: _WorkspacePanel(
                  selectedClip: _selectedClip,
                  isAnalyzing: _isAnalyzing,
                  result: _result,
                  errorMessage: _errorMessage,
                  onPickClip: _pickClip,
                  onRunAnalysis: _runAnalysis,
                ),
              ),
              const SizedBox(width: 20, height: 20),
              Expanded(
                flex: 4,
                child: _ReportPanel(result: _result),
              ),
            ];

            return Padding(
              padding: const EdgeInsets.all(24),
              child: isWide
                  ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: content)
                  : Column(
                      children: [
                        _WorkspacePanel(
                          selectedClip: _selectedClip,
                          isAnalyzing: _isAnalyzing,
                          result: _result,
                          errorMessage: _errorMessage,
                          onPickClip: _pickClip,
                          onRunAnalysis: _runAnalysis,
                        ),
                        const SizedBox(height: 20),
                        _ReportPanel(result: _result),
                      ],
                    ),
            );
          },
        ),
      ),
    );
  }
}

class _WorkspacePanel extends StatelessWidget {
  const _WorkspacePanel({
    required this.selectedClip,
    required this.isAnalyzing,
    required this.result,
    required this.errorMessage,
    required this.onPickClip,
    required this.onRunAnalysis,
  });

  final PlatformFile? selectedClip;
  final bool isAnalyzing;
  final AnalysisResult? result;
  final String? errorMessage;
  final VoidCallback onPickClip;
  final VoidCallback onRunAnalysis;

  @override
  Widget build(BuildContext context) {
    final canAnalyze = selectedClip != null && !isAnalyzing;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const _SectionTitle(
                  title: 'Analiza klipu',
                  subtitle: 'Wybierz plik wideo, uruchom analize i zobacz wynik.',
                ),
                const SizedBox(height: 24),
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    FilledButton.icon(
                      onPressed: onPickClip,
                      icon: const Icon(Icons.video_file_outlined),
                      label: const Text('Wybierz klip'),
                    ),
                    FilledButton.tonalIcon(
                      onPressed: canAnalyze ? onRunAnalysis : null,
                      icon: isAnalyzing
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.analytics_outlined),
                      label: Text(isAnalyzing ? 'Analizuje...' : 'Analizuj'),
                    ),
                  ],
                ),
                const SizedBox(height: 20),
                _ClipInfo(selectedClip: selectedClip),
                if (isAnalyzing) ...[
                  const SizedBox(height: 16),
                  const _AnalysisProgress(),
                ],
                if (errorMessage != null) ...[
                  const SizedBox(height: 12),
                  _InfoBox(title: 'Blad analizy', body: errorMessage!),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),
        _VideoPreviewCard(selectedClip: selectedClip, result: result),
        const SizedBox(height: 20),
        _AnnotatedClipCard(result: result),
      ],
    );
  }
}

class _ClipInfo extends StatelessWidget {
  const _ClipInfo({required this.selectedClip});

  final PlatformFile? selectedClip;

  @override
  Widget build(BuildContext context) {
    final clip = selectedClip;
    if (clip == null) {
      return const _InfoBox(
        title: 'Brak wybranego klipu',
        body: 'Wybierz plik wideo z dysku, aby odblokowac analize.',
      );
    }

    final sizeMb = clip.size / (1024 * 1024);
    return _InfoBox(
      title: clip.name,
      body: 'Rozmiar: ${sizeMb.toStringAsFixed(2)} MB',
    );
  }
}

class _VideoPreviewCard extends StatefulWidget {
  const _VideoPreviewCard({required this.selectedClip, required this.result});

  final PlatformFile? selectedClip;
  final AnalysisResult? result;

  @override
  State<_VideoPreviewCard> createState() => _VideoPreviewCardState();
}

class _VideoPreviewCardState extends State<_VideoPreviewCard> {
  VideoPlayerController? _controller;
  String? _loadedUrl;

  @override
  void initState() {
    super.initState();
    _syncController();
  }

  @override
  void didUpdateWidget(covariant _VideoPreviewCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    _syncController();
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  void _syncController() {
    final relativeUrl = widget.result?.annotatedVideoUrl;
    if (relativeUrl == null) {
      _disposeController();
      return;
    }

    final nextUrl = relativeUrl.startsWith('http') ? relativeUrl : '$_backendBaseUrl$relativeUrl';
    if (_loadedUrl == nextUrl) {
      return;
    }

    _disposeController();
    _loadedUrl = nextUrl;
    final controller = VideoPlayerController.networkUrl(Uri.parse(nextUrl));
    _controller = controller;
    controller.initialize().then((_) {
      if (!mounted) {
        return;
      }
      setState(() {});
    });
  }

  void _disposeController() {
    _controller?.dispose();
    _controller = null;
    _loadedUrl = null;
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    final isReady = controller != null && controller.value.isInitialized;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _SectionTitle(
              title: 'Podglad klipu',
              subtitle: 'Po analizie odtworzysz tutaj klip z naniesionymi anotacjami.',
            ),
            const SizedBox(height: 20),
            AspectRatio(
              aspectRatio: 16 / 9,
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0xFFE9EEF5),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: const Color(0xFFD5DDE8)),
                ),
                clipBehavior: Clip.antiAlias,
                child: isReady
                    ? Stack(
                        alignment: Alignment.center,
                        children: [
                          AspectRatio(
                            aspectRatio: controller.value.aspectRatio,
                            child: VideoPlayer(controller),
                          ),
                          Positioned(
                            bottom: 16,
                            child: FilledButton.icon(
                              onPressed: () {
                                setState(() {
                                  controller.value.isPlaying ? controller.pause() : controller.play();
                                });
                              },
                              icon: Icon(controller.value.isPlaying ? Icons.pause : Icons.play_arrow),
                              label: Text(controller.value.isPlaying ? 'Pauza' : 'Odtworz'),
                            ),
                          ),
                        ],
                      )
                    : Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.play_circle_outline, size: 64, color: Color(0xFF1F4E79)),
                            const SizedBox(height: 12),
                            Text(
                              widget.result == null
                                  ? widget.selectedClip?.name ?? 'Wybierz klip do podgladu'
                                  : 'Laduje anotowany klip...',
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                          ],
                        ),
                      ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _AnnotatedClipCard extends StatelessWidget {
  const _AnnotatedClipCard({required this.result});

  final AnalysisResult? result;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Row(
          children: [
            const Icon(Icons.save_alt_outlined, color: Color(0xFF1F4E79)),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Zapis klipu z anotacjami', style: TextStyle(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 6),
                  Text(
                        result == null
                        ? 'Po analizie backend zapisze klip z naniesionymi szkieletami i alertami.'
                            : result!.annotatedVideoUrl ?? result!.annotatedVideoPath,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ReportPanel extends StatelessWidget {
  const _ReportPanel({required this.result});

  final AnalysisResult? result;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _SectionTitle(
              title: 'Raport',
              subtitle: 'Podsumowanie zostanie wypelnione po analizie.',
            ),
            const SizedBox(height: 24),
            if (result == null)
              const _InfoBox(
                title: 'Brak raportu',
                body: 'Uruchom analize, aby zobaczyc statystyki walki i liste akcji.',
              )
            else ...[
              _StatsGrid(result: result!),
              const SizedBox(height: 24),
              Text('Ataki wykryte w czasie walki', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              _EventsTable(events: result!.events),
              const SizedBox(height: 16),
              _InfoBox(title: 'Plik raportu', body: result!.reportPath),
            ],
          ],
        ),
      ),
    );
  }
}

class _StatsGrid extends StatelessWidget {
  const _StatsGrid({required this.result});

  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: [
        _StatCard(label: 'Ataki', value: '${result.attacks}'),
        _StatCard(label: 'Udane rzuty', value: '${result.successfulThrows}'),
        _StatCard(label: 'Nieudane', value: '${result.failedThrows}'),
        _StatCard(label: 'Czas', value: '${result.durationSeconds.toStringAsFixed(1)}s'),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 140,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF6F8FB),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE0E6EF)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 8),
          Text(value, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
        ],
      ),
    );
  }
}

class _EventsTable extends StatelessWidget {
  const _EventsTable({required this.events});

  final List<AnalysisEvent> events;

  @override
  Widget build(BuildContext context) {
    if (events.isEmpty) {
      return const _InfoBox(
        title: 'Brak wykrytych atakow',
        body: 'Analiza nie zwrocila zdarzen ataku dla tego klipu.',
      );
    }

    return DecoratedBox(
      decoration: BoxDecoration(
        color: const Color(0xFFF6F8FB),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE0E6EF)),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          headingTextStyle: const TextStyle(fontWeight: FontWeight.w800, color: Color(0xFF182230)),
          columns: const [
            DataColumn(label: Text('Sekunda')),
            DataColumn(label: Text('Rezultat')),
            DataColumn(label: Text('Opis')),
          ],
          rows: [
            for (final event in events)
              DataRow(
                cells: [
                  DataCell(Text('${event.timeSeconds.toStringAsFixed(1)}s')),
                  DataCell(Text(event.result)),
                  DataCell(SizedBox(width: 260, child: Text(event.description))),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _AnalysisProgress extends StatelessWidget {
  const _AnalysisProgress();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF6F8FB),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE0E6EF)),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Analiza w toku', style: TextStyle(fontWeight: FontWeight.w800)),
          SizedBox(height: 10),
          LinearProgressIndicator(),
          SizedBox(height: 8),
          Text('Przetwarzanie klipu, generowanie anotacji i raportu...'),
        ],
      ),
    );
  }
}

class _InfoBox extends StatelessWidget {
  const _InfoBox({required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF6F8FB),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE0E6EF)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text(body),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                color: const Color(0xFF182230),
                fontWeight: FontWeight.w800,
              ),
        ),
        const SizedBox(height: 6),
        Text(
          subtitle,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: const Color(0xFF475467)),
        ),
      ],
    );
  }
}
