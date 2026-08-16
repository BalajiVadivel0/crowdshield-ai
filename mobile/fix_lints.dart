import 'dart:io';

void main() {
  final dir = Directory('e:/CIT/crowdshield-ai/mobile/lib/features/authority/presentation');
  
  for (var entity in dir.listSync(recursive: true)) {
    if (entity is File && entity.path.endsWith('.dart')) {
      var content = entity.readAsStringSync();
      var changed = false;

      // Fix imports
      if (content.contains("import '../../../../core/theme/app_theme.dart';")) {
        content = content.replaceAll("import '../../../../core/theme/app_theme.dart';", "import '../../../../core/theme/app_colors.dart';");
        changed = true;
      }
      if (content.contains("import '../../../core/theme/app_theme.dart';")) {
        content = content.replaceAll("import '../../../core/theme/app_theme.dart';", "import '../../../core/theme/app_colors.dart';");
        changed = true;
      }

      // Replace AppTheme with AppColors
      final Map<String, String> replacements = {
        'AppTheme.primaryColor': 'AppColors.primary',
        'AppTheme.errorColor': 'AppColors.critical',
        'AppTheme.warningColor': 'AppColors.warning',
        'AppTheme.successColor': 'AppColors.safe',
      };

      for (var entry in replacements.entries) {
        if (content.contains(entry.key)) {
          content = content.replaceAll(entry.key, entry.value);
          changed = true;
        }
      }

      if (changed) {
        entity.writeAsStringSync(content);
        print('Updated: ${entity.path}');
      }
    }
  }
}
