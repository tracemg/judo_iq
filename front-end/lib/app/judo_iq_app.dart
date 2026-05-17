import 'package:flutter/material.dart';

import '../core/theme/app_theme.dart';
import '../features/analysis/analysis_page.dart';

class JudoIqApp extends StatelessWidget {
  const JudoIqApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'JudoIQ',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      home: const AnalysisPage(),
    );
  }
}
