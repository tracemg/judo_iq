import 'package:flutter/material.dart';

class AppTheme {
  const AppTheme._();

  static ThemeData light() {
    return ThemeData(
      scaffoldBackgroundColor: const Color(0xFFF6F8FB),
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1F4E79)),
      cardTheme: CardThemeData(
        color: Colors.white,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: const BorderSide(color: Color(0xFFE0E6EF)),
        ),
      ),
      useMaterial3: true,
    );
  }
}
