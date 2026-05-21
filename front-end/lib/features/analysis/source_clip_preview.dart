import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../../core/models/analysis_progress.dart';
import '../../core/video/blob_video_url.dart';

class SourceClipPreview extends StatefulWidget {
  const SourceClipPreview({
    super.key,
    required this.clip,
    this.analysisProgress,
    this.isAnalyzing = false,
  });

  final PlatformFile clip;
  final AnalysisProgress? analysisProgress;
  final bool isAnalyzing;

  @override
  State<SourceClipPreview> createState() => _SourceClipPreviewState();
}

class _SourceClipPreviewState extends State<SourceClipPreview> {
  VideoPlayerController? _controller;
  String? _blobUrl;
  String? _loadedClipKey;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _loadClip();
  }

  @override
  void didUpdateWidget(covariant SourceClipPreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    final clipKey = '${widget.clip.name}:${widget.clip.size}';
    if (clipKey != _loadedClipKey) {
      _loadClip();
    } else {
      _syncPlaybackPosition();
    }
  }

  @override
  void dispose() {
    _disposeController();
    super.dispose();
  }

  void _loadClip() {
    final bytes = widget.clip.bytes;
    if (bytes == null) {
      setState(() {
        _errorMessage = 'Nie mozna wczytac podgladu. Wybierz klip ponownie.';
      });
      return;
    }

    final clipKey = '${widget.clip.name}:${widget.clip.size}';
    if (_loadedClipKey == clipKey) {
      return;
    }

    _disposeController();
    _loadedClipKey = clipKey;
    _errorMessage = null;

    final blobUrl = blobUrlFromBytes(bytes, widget.clip.name);
    if (blobUrl == null) {
      setState(() {
        _errorMessage = 'Podglad wideo jest dostepny tylko w wersji web.';
      });
      return;
    }

    _blobUrl = blobUrl;
    final controller = VideoPlayerController.networkUrl(Uri.parse(blobUrl));
    _controller = controller;
    controller.initialize().then((_) {
      if (!mounted) {
        return;
      }
      _syncPlaybackPosition(force: true);
      setState(() {});
    }).catchError((Object error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = 'Blad ladowania podgladu: $error';
      });
    });
  }

  void _syncPlaybackPosition({bool force = false}) {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized || !widget.isAnalyzing) {
      return;
    }

    final seconds = widget.analysisProgress?.timeSeconds;
    if (seconds == null) {
      return;
    }

    final target = Duration(milliseconds: (seconds * 1000).round());
    final deltaMs = (controller.value.position - target).inMilliseconds.abs();
    if (!force && deltaMs < 400) {
      return;
    }

    controller.seekTo(target);
  }

  void _disposeController() {
    _controller?.dispose();
    _controller = null;
    if (_blobUrl != null) {
      revokeBlobVideoUrl(_blobUrl!);
      _blobUrl = null;
    }
    _loadedClipKey = null;
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    final isReady = controller != null && controller.value.isInitialized;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Podglad klipu',
          style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 4),
        Text(
          widget.isAnalyzing
              ? 'Podczas analizy wskaznik przesuwa sie do aktualnie przetwarzanej sekundy.'
              : 'Odtworz wybrany klip przed uruchomieniem analizy.',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: const Color(0xFF475467)),
        ),
        const SizedBox(height: 12),
        AspectRatio(
          aspectRatio: 16 / 9,
          child: Container(
            decoration: BoxDecoration(
              color: const Color(0xFF101828),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: const Color(0xFFD5DDE8)),
            ),
            clipBehavior: Clip.antiAlias,
            child: _errorMessage != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(
                        _errorMessage!,
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Colors.white70),
                      ),
                    ),
                  )
                : isReady
                    ? Stack(
                        fit: StackFit.expand,
                        children: [
                          FittedBox(
                            fit: BoxFit.contain,
                            child: SizedBox(
                              width: controller.value.size.width,
                              height: controller.value.size.height,
                              child: VideoPlayer(controller),
                            ),
                          ),
                          if (widget.isAnalyzing)
                            Positioned(
                              top: 12,
                              left: 12,
                              child: DecoratedBox(
                                decoration: BoxDecoration(
                                  color: Colors.black.withValues(alpha: 0.65),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: const Padding(
                                  padding: EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      SizedBox(
                                        width: 14,
                                        height: 14,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                          color: Colors.white,
                                        ),
                                      ),
                                      SizedBox(width: 8),
                                      Text(
                                        'Analiza w toku',
                                        style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          Positioned(
                            bottom: 12,
                            left: 0,
                            right: 0,
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                FilledButton.icon(
                                  onPressed: () {
                                    setState(() {
                                      controller.value.isPlaying ? controller.pause() : controller.play();
                                    });
                                  },
                                  icon: Icon(controller.value.isPlaying ? Icons.pause : Icons.play_arrow),
                                  label: Text(controller.value.isPlaying ? 'Pauza' : 'Odtworz'),
                                ),
                              ],
                            ),
                          ),
                        ],
                      )
                    : const Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            CircularProgressIndicator(color: Colors.white70),
                            SizedBox(height: 12),
                            Text('Ladowanie podgladu...', style: TextStyle(color: Colors.white70)),
                          ],
                        ),
                      ),
          ),
        ),
        if (isReady && widget.analysisProgress?.timeSeconds != null) ...[
          const SizedBox(height: 8),
          Text(
            'Aktualnie analizowana sekunda: ${widget.analysisProgress!.timeSeconds!.toStringAsFixed(1)} s',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: const Color(0xFF475467),
                  fontWeight: FontWeight.w600,
                ),
          ),
        ],
      ],
    );
  }
}
