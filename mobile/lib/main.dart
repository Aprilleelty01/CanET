import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

String defaultApiBaseForRuntime() {
  if (kIsWeb) {
    final base = Uri.base;
    final scheme = base.scheme == 'https' ? 'https' : 'http';
    final host = base.host.isEmpty ? '127.0.0.1' : base.host;
    return '$scheme://$host:8000';
  }

  if (Platform.isAndroid) {
    return 'http://10.0.2.2:8000';
  }
  return 'http://127.0.0.1:8000';
}

void main() {
  runApp(const MyApp());
}

const Color polyuRed = Color(0xFF8F1329);

const Map<String, String> sentimentZhMap = {
  'sadness': '悲傷',
  'fear': '恐懼',
  'neutral': '中性',
  'surprised': '驚訝',
  'love': '愛',
  'anger': '憤怒',
  'joy': '喜悅',
  'expect': '期待',
  'worry': '擔心',
  'excited': '興奮',
  'positive': '正面',
  'negative': '負面',
};

const Map<String, String> emotionZhMap = {
  'sadness': '悲傷',
  'fear': '恐懼',
  'neutral': '中性',
  'surprised': '驚訝',
  'love': '愛',
  'anger': '憤怒',
  'joy': '喜悅',
  'expect': '期待',
  'worry': '擔心',
  'excited': '興奮',
};

const Map<String, String> attitudeZhMap = {
  'respectful': '尊重',
  'non-respectful': '不尊重',
  'irony': '反諷',
  'playful': '玩笑',
  'mockery': '嘲諷',
  'warning': '警告',
  'certain': '肯定',
};

const Map<String, String> relationshipZhMap = {
  'family': '家庭',
  'friends': '朋友',
  'hierarchical': '階層關係',
  'professional': '專業關係',
  'strangers': '陌生人',
};

String _bilingualLabel(String value, Map<String, String> mapping) {
  final raw = value.trim();
  if (raw.isEmpty) {
    return raw;
  }
  final lower = raw.toLowerCase();
  final zh = mapping[lower];
  return zh == null ? raw : '$zh $raw';
}

String _zhOnlyLabel(String value, Map<String, String> mapping) {
  final raw = value.trim();
  if (raw.isEmpty) {
    return raw;
  }
  final zh = mapping[raw.toLowerCase()];
  return zh ?? raw;
}

String _zhListLabel(String value, Map<String, String> mapping) {
  final parts = value
      .split(',')
      .map((e) => e.trim())
      .where((e) => e.isNotEmpty)
      .map((e) => _zhOnlyLabel(e, mapping))
      .toList();
  if (parts.isEmpty) {
    return value.trim();
  }
  return parts.join('、');
}

String _classifySfpMeaning(String meaning) {
  final lower = meaning.toLowerCase();
  if (lower.contains('question') || lower.contains('疑問') || lower.contains('詢問')) {
    return 'question';
  }
  if (lower.contains('soft') || lower.contains('軟化') || lower.contains('gentle') || lower.contains('polite')) {
    return 'softening tone';
  }
  if (lower.contains('exclamation') || lower.contains('感歎') || lower.contains('驚嘆')) {
    return 'exclamation';
  }
  if (lower.contains('emphasis') || lower.contains('強調') || lower.contains('certain')) {
    return 'emphasis';
  }
  if (lower.contains('playful') || lower.contains('輕鬆') || lower.contains('俏皮')) {
    return 'playful';
  }
  if (lower.contains('urging') || lower.contains('催促') || lower.contains('敦促')) {
    return 'urging';
  }
  if (lower.contains('suggest') || lower.contains('建議') || lower.contains('提議')) {
    return 'suggestion';
  }
  if (lower.contains('warning') || lower.contains('警告') || lower.contains('提醒')) {
    return 'warning';
  }
  if (lower.contains('agreement') || lower.contains('同意') || lower.contains('贊同')) {
    return 'agreement';
  }
  return 'particle';
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Cantonese Translator',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: polyuRed,
          primary: polyuRed,
          surface: Colors.white,
        ),
        scaffoldBackgroundColor: Colors.white,
        appBarTheme: const AppBarTheme(
          backgroundColor: polyuRed,
          foregroundColor: Colors.white,
        ),
        navigationBarTheme: NavigationBarThemeData(
          backgroundColor: Colors.white,
          indicatorColor: polyuRed.withValues(alpha: 0.15),
          labelTextStyle: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.selected)) {
              return const TextStyle(color: polyuRed, fontWeight: FontWeight.w600);
            }
            return const TextStyle(color: Colors.black87);
          }),
        ),
        useMaterial3: true,
      ),
      home: const CanETSplashPage(),
    );
  }
}

class CanETSplashPage extends StatefulWidget {
  const CanETSplashPage({super.key});

  @override
  State<CanETSplashPage> createState() => _CanETSplashPageState();
}

class _CanETSplashPageState extends State<CanETSplashPage> {
  @override
  void initState() {
    super.initState();
    Future.delayed(const Duration(milliseconds: 1400), () {
      if (!mounted) {
        return;
      }
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const TranslatorPage()),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'CanET',
              style: TextStyle(
                fontSize: 40,
                fontWeight: FontWeight.w800,
                color: polyuRed,
                letterSpacing: 1.5,
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: 160,
              child: LinearProgressIndicator(
                minHeight: 6,
                color: polyuRed,
                backgroundColor: const Color(0xFFF2DDE1),
                borderRadius: BorderRadius.circular(20),
              ),
            ),
            const SizedBox(height: 14),
            const Text('正在載入粵語翻譯器...'),
          ],
        ),
      ),
    );
  }
}

class TranslatorPage extends StatefulWidget {
  const TranslatorPage({super.key});

  @override
  State<TranslatorPage> createState() => _TranslatorPageState();
}

class _TranslatorPageState extends State<TranslatorPage> {
  int _selectedTab = 2;

  static const List<String> _tabTitles = [
    '助語詞字典',
    '粗口',
    '主頁',
    '設定',
    '紀錄',
  ];

  final TextEditingController _textController = TextEditingController();
  final TextEditingController _apiBaseController =
      TextEditingController(text: defaultApiBaseForRuntime());
  final TextEditingController _openAiApiKeyController = TextEditingController();
  final TextEditingController _foulSearchController = TextEditingController();
  final TextEditingController _sfpSearchController = TextEditingController();
  final TextEditingController _foulCombinedController = TextEditingController();

  bool _useFuzzy = true;
  bool _useSentiment = true;
  bool _useLm = false;
  bool _allowSimplified = false;

  bool _isLoading = false;
  bool _isHealthChecking = false;
  bool _isSfpLoading = false;
  bool _isFoulLoading = false;
  bool _isHistoryLoading = false;
  bool _isAutoConnectingBackend = false;
  bool _isAdvancedSearching = false;
  bool _useOpenAiAdvanced = false;
  bool _isFoulCombinedLoading = false;

  double? _estimatedRunSeconds;
  double? _actualRunSeconds;
  double? _networkMbps;
  int _liveProgressPercent = 0;
  double _estimatedRemainingSeconds = 0;
  Timer? _progressTimer;

  String? _error;
  String? _healthMessage;
  String? _sfpError;
  String? _foulError;
  String? _historyError;
  String? _advancedError;
  String? _foulCombinedError;

  TranslationResponse? _result;
  List<SfpEntry> _sfpEntries = [];
  List<SfpEntry> _filteredSfpEntries = [];
  List<FoulEntry> _foulEntries = [];
  List<HistoryEntry> _historyEntries = [];
  List<String> _emotionOptions = [];
  List<String> _attitudeOptions = [];
  List<String> _relationshipOptions = [];
  final Set<String> _selectedEmotions = <String>{};
  final Set<String> _selectedAttitudes = <String>{};
  final Set<String> _selectedRelationships = <String>{};
  AdvancedSearchResponse? _advancedResult;
  TranslationResponse? _foulCombinedResult;

  @override
  void initState() {
    super.initState();
    unawaited(_autoConnectBackend());
    _fetchAdvancedOptions();
    _fetchSfpEntries();
    _fetchFoulEntries();
    _fetchHistory();
  }

  List<String> _candidateApiBases() {
    final current = _apiBaseController.text.trim();
    final out = <String>[];

    void addBase(String value) {
      final v = value.trim();
      if (v.isEmpty) {
        return;
      }
      if (!out.contains(v)) {
        out.add(v);
      }
    }

    addBase(current);
    addBase(defaultApiBaseForRuntime());
    addBase('http://127.0.0.1:8000');
    addBase('http://localhost:8000');

    if (kIsWeb) {
      final base = Uri.base;
      final scheme = base.scheme == 'https' ? 'https' : 'http';
      final host = base.host;
      if (host.isNotEmpty) {
        addBase('$scheme://$host:8000');
      }
    }

    return out;
  }

  Future<void> _autoConnectBackend({bool showResult = false}) async {
    if (_isAutoConnectingBackend) {
      return;
    }

    setState(() {
      _isAutoConnectingBackend = true;
      if (showResult) {
        _healthMessage = null;
      }
    });

    String? matched;
    for (final base in _candidateApiBases()) {
      try {
        final resp = await http
            .get(Uri.parse('$base/health'))
            .timeout(const Duration(seconds: 3));
        if (resp.statusCode != 200) {
          continue;
        }

        final body = jsonDecode(resp.body) as Map<String, dynamic>;
        if (body['ok'] == true) {
          matched = base;
          break;
        }
      } catch (_) {
        continue;
      }
    }

    if (!mounted) {
      return;
    }

    final matchedBase = matched;

    setState(() {
      _isAutoConnectingBackend = false;
      if (matchedBase != null) {
        _apiBaseController.text = matchedBase;
      }
    });

    if (matchedBase != null) {
      unawaited(_fetchSfpEntries());
      unawaited(_fetchFoulEntries());
      unawaited(_fetchHistory());
      unawaited(_fetchAdvancedOptions());
    }
  }

  @override
  void dispose() {
    _progressTimer?.cancel();
    _textController.dispose();
    _apiBaseController.dispose();
    _openAiApiKeyController.dispose();
    _foulSearchController.dispose();
    _sfpSearchController.dispose();
    _foulCombinedController.dispose();
    super.dispose();
  }

  Uri _buildUri(String path) {
    final base = _apiBaseController.text.trim();
    return Uri.parse('$base$path');
  }

  double _estimateRunTime(String input) {
    final chars = input.length;
    var est = 1.2 + (chars / 45.0);
    if (_useLm) {
      est += 1.0;
    }
    if (_useSentiment) {
      est += 0.4;
    }
    return est.clamp(0.8, 20.0);
  }

  Future<double?> _measureNetworkMbps() async {
    try {
      final started = DateTime.now();
      final response = await http.get(_buildUri('/sfp'));
      final elapsedMs = DateTime.now().difference(started).inMilliseconds;
      if (response.statusCode != 200 || elapsedMs <= 0) {
        return null;
      }
      final bits = utf8.encode(response.body).length * 8.0;
      return bits / (elapsedMs / 1000.0) / 1000000.0;
    } catch (_) {
      return null;
    }
  }

  void _startLiveProgressTicker(double estimatedSeconds) {
    _progressTimer?.cancel();
    final estimatedMs = (estimatedSeconds * 1000).toInt().clamp(800, 20000);
    final startedAt = DateTime.now();

    setState(() {
      _liveProgressPercent = 0;
      _estimatedRemainingSeconds = estimatedSeconds;
    });

    _progressTimer = Timer.periodic(const Duration(milliseconds: 200), (timer) {
      final elapsedMs = DateTime.now().difference(startedAt).inMilliseconds;
      final progress = ((elapsedMs / estimatedMs) * 100).clamp(0, 95).round();
      final remaining = ((estimatedMs - elapsedMs).clamp(0, estimatedMs)) / 1000.0;

      if (!mounted || !_isLoading) {
        timer.cancel();
        return;
      }

      setState(() {
        _liveProgressPercent = progress;
        _estimatedRemainingSeconds = remaining;
      });
    });
  }

  void _finishLiveProgressTicker() {
    _progressTimer?.cancel();
    _progressTimer = null;
    if (!mounted) {
      return;
    }
    setState(() {
      _liveProgressPercent = 100;
      _estimatedRemainingSeconds = 0;
    });
  }

  Future<void> _checkHealth() async {
    setState(() {
      _isHealthChecking = true;
      _healthMessage = null;
    });

    try {
      final response = await http.get(_buildUri('/health'));
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final ok = body['ok'] == true;
        setState(() {
          _healthMessage = ok
              ? '後端正常。'
              : '後端有回應，但狀態不是 ok。';
        });
      } else {
        setState(() {
          _healthMessage =
              '後端健康檢查失敗（${response.statusCode}）：${response.body}';
        });
      }
    } catch (e) {
      setState(() {
        _healthMessage = '後端健康檢查錯誤：$e';
      });
    } finally {
      setState(() {
        _isHealthChecking = false;
      });
    }
  }

  Future<void> _fetchSfpEntries() async {
    setState(() {
      _isSfpLoading = true;
      _sfpError = null;
    });

    try {
      final response = await http.get(_buildUri('/sfp'));
      if (response.statusCode != 200) {
        setState(() {
          _sfpError =
            '載入助語詞失敗（${response.statusCode}）：${response.body}';
        });
        return;
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final items = (body['items'] as List<dynamic>? ?? <dynamic>[])
          .map((e) => SfpEntry.fromJson(e as Map<String, dynamic>))
          .toList();
      setState(() {
        _sfpEntries = items;
        _filteredSfpEntries = items;
      });
    } catch (e) {
      setState(() {
        _sfpError = '助語詞請求錯誤：$e';
      });
    } finally {
      setState(() {
        _isSfpLoading = false;
      });
    }
  }

  Future<void> _fetchFoulEntries() async {
    setState(() {
      _isFoulLoading = true;
      _foulError = null;
    });

    try {
      final response = await http.get(_buildUri('/foul'));
      if (response.statusCode != 200) {
        setState(() {
          _foulError =
            '載入粗口詞條失敗（${response.statusCode}）：${response.body}';
        });
        return;
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final items = (body['items'] as List<dynamic>? ?? <dynamic>[])
          .map((e) => FoulEntry.fromJson(e as Map<String, dynamic>))
          .toList();
      setState(() {
        _foulEntries = items;
      });
    } catch (e) {
      setState(() {
        _foulError = '粗口詞條請求錯誤：$e';
      });
    } finally {
      setState(() {
        _isFoulLoading = false;
      });
    }
  }

  void _filterSfpEntries() {
    final query = _sfpSearchController.text.trim().toLowerCase();
    if (query.isEmpty) {
      setState(() {
        _filteredSfpEntries = _sfpEntries;
      });
      return;
    }

    setState(() {
      _filteredSfpEntries = _sfpEntries.where((entry) {
        final blob = '${entry.character} ${entry.jyutping} ${entry.engpinyin} ${entry.meaning}'.toLowerCase();
        return blob.contains(query);
      }).toList();
    });
  }

  Future<void> _fetchHistory() async {
    setState(() {
      _isHistoryLoading = true;
      _historyError = null;
    });

    try {
      final response = await http.get(_buildUri('/history?limit=100'));
      if (response.statusCode != 200) {
        setState(() {
          _historyError =
            '載入翻譯紀錄失敗（${response.statusCode}）：${response.body}';
        });
        return;
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final items = (body['items'] as List<dynamic>? ?? <dynamic>[])
          .map((e) => HistoryEntry.fromJson(e as Map<String, dynamic>))
          .toList();
      setState(() {
        _historyEntries = items;
      });
    } catch (e) {
      setState(() {
        _historyError = '翻譯紀錄請求錯誤：$e';
      });
    } finally {
      setState(() {
        _isHistoryLoading = false;
      });
    }
  }

  Future<void> _fetchAdvancedOptions() async {
    try {
      final response = await http
          .get(_buildUri('/advanced_options'))
          .timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) {
        return;
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;

      List<String> parseList(String key) {
        final raw = body[key] as List<dynamic>? ?? <dynamic>[];
        return raw.map((e) => e.toString()).where((e) => e.trim().isNotEmpty).toList();
      }

      if (!mounted) {
        return;
      }

      setState(() {
        _emotionOptions = parseList('emotion_options');
        _attitudeOptions = parseList('attitude_options');
        _relationshipOptions = parseList('relationship_options');
      });
    } catch (_) {
      // Keep UI usable even if options endpoint is temporarily unavailable.
    }
  }

  Future<void> _runAdvancedSearch() async {
    final input = _textController.text.trim();
    if (input.isEmpty) {
      setState(() {
        _advancedError = '請先輸入文字。';
      });
      return;
    }

    if (_selectedEmotions.isEmpty && _selectedAttitudes.isEmpty && _selectedRelationships.isEmpty) {
      setState(() {
        _advancedError = '請至少選擇一個進階搜尋標籤。';
      });
      return;
    }

    setState(() {
      _isAdvancedSearching = true;
      _advancedError = null;
      _advancedResult = null;
    });

    try {
      final response = await http
          .post(
            _buildUri('/advanced_search'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'text': input,
              'emotion_tags': _selectedEmotions.toList(),
              'attitude_tags': _selectedAttitudes.toList(),
              'relationship_tags': _selectedRelationships.toList(),
              'use_openai': _useOpenAiAdvanced,
              'openai_api_key': _openAiApiKeyController.text.trim(),
            }),
          )
          .timeout(const Duration(seconds: 45));

      if (response.statusCode != 200) {
        setState(() {
          _advancedError =
              '進階搜尋失敗（${response.statusCode}）：${response.body}';
        });
        return;
      }

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      if (data.containsKey('error')) {
        setState(() {
          _advancedError = data['error']?.toString() ?? '未知後端錯誤。';
        });
        return;
      }

      setState(() {
        _advancedResult = AdvancedSearchResponse.fromJson(data);
      });
    } catch (e) {
      setState(() {
        _advancedError = '進階搜尋請求錯誤：$e';
      });
    } finally {
      setState(() {
        _isAdvancedSearching = false;
      });
    }
  }

  Future<void> _runFoulCombinedTranslation() async {
    final input = _foulCombinedController.text.trim();
    if (input.isEmpty) {
      setState(() {
        _foulCombinedError = '請先輸入文字。';
        _foulCombinedResult = null;
      });
      return;
    }

    setState(() {
      _isFoulCombinedLoading = true;
      _foulCombinedError = null;
      _foulCombinedResult = null;
    });

    try {
      final response = await http
          .post(
            _buildUri('/foul_combined_translate'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'text': input,
              'use_fuzzy': _useFuzzy,
              'use_sentiment': _useSentiment,
              'use_lm': _useLm,
              'allow_simplified': _allowSimplified,
            }),
          )
          .timeout(const Duration(seconds: 30));

      if (response.statusCode != 200) {
        setState(() {
          _foulCombinedError =
              'Combined foul translation failed (${response.statusCode}): ${response.body}';
        });
        return;
      }

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      if (data.containsKey('error')) {
        setState(() {
          _foulCombinedError = data['error']?.toString() ?? '未知後端錯誤。';
        });
        return;
      }

      setState(() {
        _foulCombinedResult = TranslationResponse.fromJson(data);
      });
    } catch (e) {
      setState(() {
        _foulCombinedError = '粗口整合翻譯請求錯誤：$e';
      });
    } finally {
      setState(() {
        _isFoulCombinedLoading = false;
      });
    }
  }

  Future<void> _translateText() async {
    final input = _textController.text.trim();
    if (input.isEmpty) {
      setState(() {
        _error = '請先輸入文字。';
        _result = null;
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _error = null;
      _estimatedRunSeconds = _estimateRunTime(input);
      _actualRunSeconds = null;
      _networkMbps = null;
    });
    _startLiveProgressTicker(_estimatedRunSeconds ?? 1.0);

    final startedAt = DateTime.now();
    _networkMbps = await _measureNetworkMbps();

    try {
      final payload = jsonEncode({
        'text': input,
        'use_fuzzy': _useFuzzy,
        'use_sentiment': _useSentiment,
        'use_lm': _useLm,
        'allow_simplified': _allowSimplified,
      });

      http.Response? response;
      String? usedBase;
      final tried = <String>[];

      for (final base in _candidateApiBases()) {
        tried.add(base);
        try {
          final resp = await http
              .post(
                Uri.parse('$base/translate'),
                headers: {'Content-Type': 'application/json'},
                body: payload,
              )
              .timeout(const Duration(seconds: 20));

          if (resp.statusCode == 200) {
            response = resp;
            usedBase = base;
            break;
          }

          // Keep last response for diagnostics and continue trying fallback hosts.
          response = resp;
          usedBase = base;
        } catch (_) {
          continue;
        }
      }

      if (response == null) {
        setState(() {
          _error = '翻譯失敗：無法連線後端。已嘗試：${tried.join(', ')}';
          _result = null;
        });
        return;
      }

      final resp = response;

      if (usedBase != null && _apiBaseController.text.trim() != usedBase) {
        _apiBaseController.text = usedBase;
      }

      if (resp.statusCode != 200) {
        setState(() {
          _error =
              '翻譯請求失敗（${resp.statusCode}），路徑 ${usedBase ?? _apiBaseController.text.trim()}：${resp.body}';
          _result = null;
        });
        return;
      }

      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      if (data.containsKey('error')) {
        setState(() {
          _error = data['error']?.toString() ?? '未知後端錯誤。';
          _result = null;
        });
        return;
      }

      setState(() {
        _result = TranslationResponse.fromJson(data);
      });
    } catch (e) {
      setState(() {
        _error = '請求錯誤：$e';
        _result = null;
      });
    } finally {
      final actualMs = DateTime.now().difference(startedAt).inMilliseconds;
      _finishLiveProgressTicker();
      setState(() {
        _isLoading = false;
        _actualRunSeconds = actualMs / 1000.0;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_tabTitles[_selectedTab]),
      ),
      body: SafeArea(
        child: IndexedStack(
          index: _selectedTab,
          children: [
            _buildSfpTab(),
            _buildFoulTab(),
            _buildHomeTab(),
            _buildSettingsTab(),
            _buildHistoryTab(),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedTab,
        onDestinationSelected: (index) {
          setState(() {
            _selectedTab = index;
          });
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.menu_book_outlined),
            selectedIcon: Icon(Icons.menu_book),
            label: '助語詞',
          ),
          NavigationDestination(
            icon: Icon(Icons.gpp_bad_outlined),
            selectedIcon: Icon(Icons.gpp_bad),
            label: '粗口',
          ),
          NavigationDestination(
            icon: Icon(Icons.home_outlined, size: 30),
            selectedIcon: Icon(Icons.home, size: 34),
            label: '主頁',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: '設定',
          ),
          NavigationDestination(
            icon: Icon(Icons.history_outlined),
            selectedIcon: Icon(Icons.history),
            label: '紀錄',
          ),
        ],
      ),
    );
  }

  Widget _buildHomeTab() {
    return AbsorbPointer(
      absorbing: _isLoading,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('粵語翻譯', style: TextStyle(fontSize: 18)),
          const SizedBox(height: 6),
          const Card(
            color: Color(0xFFFFF9E6),
            child: Padding(
              padding: EdgeInsets.all(12),
              child: Text(
                '使用方法：1）輸入文字。2）按「翻譯」。3）可於下方分頁查看助語詞、粗口、設定與紀錄。',
              ),
            ),
          ),
          const SizedBox(height: 8),
          const SizedBox(height: 10),
          TextField(
            controller: _textController,
            maxLines: 3,
            readOnly: _isLoading,
            decoration: const InputDecoration(
              labelText: '請輸入粵語文字',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          ExpansionTile(
            title: const Text('進階搜尋（AI）'),
            childrenPadding: const EdgeInsets.only(bottom: 8),
            children: [
              _buildTagSelector(
                title: '情感標籤',
                options: _emotionOptions,
                selected: _selectedEmotions,
                zhMap: emotionZhMap,
              ),
              _buildTagSelector(
                title: '態度標籤',
                options: _attitudeOptions,
                selected: _selectedAttitudes,
                zhMap: attitudeZhMap,
              ),
              _buildTagSelector(
                title: '關係標籤',
                options: _relationshipOptions,
                selected: _selectedRelationships,
                zhMap: relationshipZhMap,
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: (_isLoading || _isAdvancedSearching) ? null : _runAdvancedSearch,
                icon: const Icon(Icons.auto_awesome),
                label: Text(_isAdvancedSearching ? '執行中...' : '執行進階搜尋'),
              ),
              if (_advancedError != null) ...[
                const SizedBox(height: 8),
                Text(
                  _advancedError!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
              if (_advancedResult != null) ...[
                const SizedBox(height: 8),
                _buildAdvancedResultView(_advancedResult!),
              ],
            ],
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _isLoading ? null : _translateText,
            child: Text(_isLoading ? '翻譯中...' : '翻譯'),
          ),
          const SizedBox(height: 12),
          if (_isLoading || _liveProgressPercent > 0)
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                LinearProgressIndicator(value: _liveProgressPercent / 100),
                const SizedBox(height: 6),
                Text('進度：$_liveProgressPercent%'),
                Text('預計剩餘：${_estimatedRemainingSeconds.toStringAsFixed(1)}秒'),
              ],
            ),
          if (_estimatedRunSeconds != null || _actualRunSeconds != null || _networkMbps != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (_estimatedRunSeconds != null)
                      Text('預計需時：${_estimatedRunSeconds!.toStringAsFixed(1)}秒'),
                    if (_actualRunSeconds != null)
                      Text('實際需時：${_actualRunSeconds!.toStringAsFixed(2)}秒'),
                    Text(
                      _networkMbps == null
                          ? '網速：未能取得'
                          : '網速：約 ${_networkMbps!.toStringAsFixed(2)} Mbps',
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 16),
          if (_error != null)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text(_error!),
              ),
            ),
          if (_result != null) _buildResultView(_result!),
        ],
      ),
    );
  }

  Widget _buildTagSelector({
    required String title,
    required List<String> options,
    required Set<String> selected,
    Map<String, String>? zhMap,
  }) {
    if (options.isEmpty) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: options.map((option) {
              final isSelected = selected.contains(option);
              final label = zhMap == null ? option : _zhOnlyLabel(option, zhMap);
              return ChoiceChip(
                label: Text(label),
                selected: isSelected,
                onSelected: (value) {
                  setState(() {
                    if (value) {
                      selected.add(option);
                    } else {
                      selected.remove(option);
                    }
                  });
                },
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildSfpTab() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            const Expanded(child: Text('助語詞字典', style: TextStyle(fontSize: 18))),
            OutlinedButton(
              onPressed: _isSfpLoading ? null : _fetchSfpEntries,
              child: Text(_isSfpLoading ? '載入中...' : '重新整理'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _sfpSearchController,
          decoration: const InputDecoration(
            labelText: '搜尋助語詞詞條',
            border: OutlineInputBorder(),
          ),
          onChanged: (_) => _filterSfpEntries(),
        ),
        const SizedBox(height: 12),
        if (_sfpError != null) Text(_sfpError!),
        if (_filteredSfpEntries.isEmpty && !_isSfpLoading)
          const Text('找不到助語詞資料。'),
        ..._filteredSfpEntries.map(
          (item) => Card(
            child: ListTile(
              title: Text(item.character),
              subtitle: Text(
                '粵拼: ${item.jyutping}\n意思: ${item.meaning}\n英拼: ${item.engpinyin}',
              ),
              isThreeLine: true,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildFoulTab() {
    final query = _foulSearchController.text.trim().toLowerCase();
    final filtered = _foulEntries.where((entry) {
      if (query.isEmpty) {
        return true;
      }
      final blob =
          '${entry.canonical} ${entry.literal} ${entry.desired} ${entry.variations.join(' ')}'
              .toLowerCase();
      return blob.contains(query);
    }).toList();

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text('粗口整合翻譯', style: TextStyle(fontSize: 18)),
        const SizedBox(height: 10),
        TextField(
          controller: _foulCombinedController,
          maxLines: 3,
          decoration: const InputDecoration(
            labelText: '請輸入要做粗口整合翻譯的句子',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 10),
        FilledButton.icon(
          onPressed: _isFoulCombinedLoading ? null : _runFoulCombinedTranslation,
          icon: const Icon(Icons.translate),
          label: Text(_isFoulCombinedLoading ? '翻譯中...' : '執行粗口整合翻譯'),
        ),
        if (_foulCombinedError != null) ...[
          const SizedBox(height: 8),
          Text(
            _foulCombinedError!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ],
        if (_foulCombinedResult != null) ...[
          const SizedBox(height: 10),
          _buildResultView(_foulCombinedResult!),
        ],
        const Divider(height: 28),
        Row(
          children: [
            const Expanded(child: Text('粗口詞條', style: TextStyle(fontSize: 18))),
            OutlinedButton(
              onPressed: _isFoulLoading ? null : _fetchFoulEntries,
              child: Text(_isFoulLoading ? '載入中...' : '重新整理'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _foulSearchController,
          decoration: const InputDecoration(
            labelText: '搜尋粗口詞條',
            border: OutlineInputBorder(),
          ),
          onChanged: (_) => setState(() {}),
        ),
        const SizedBox(height: 12),
        if (_foulError != null) Text(_foulError!),
        if (filtered.isEmpty && !_isFoulLoading)
          const Text('找不到符合的粗口詞條。'),
        ...filtered.map(
          (item) => Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('中文: ${item.canonical}',
                      style: const TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text('引申意思: ${item.desired}'),
                  Text('字面意思: ${item.literal}'),
                  Text(
                    '變體: ${item.variations.isEmpty ? '（無）' : item.variations.join(', ')}',
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildSettingsTab() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text('設定', style: TextStyle(fontSize: 18)),
        const SizedBox(height: 12),
        TextField(
          controller: _apiBaseController,
          decoration: const InputDecoration(
            labelText: '後端網址',
            hintText: 'http://127.0.0.1:8000（網頁版會自動偵測主機）',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 10),
        OutlinedButton(
          onPressed: _isHealthChecking ? null : _checkHealth,
          child: Text(_isHealthChecking ? '檢查中...' : '檢查後端狀態'),
        ),
        if (_healthMessage != null) ...[
          const SizedBox(height: 8),
          Text(_healthMessage!),
        ],
        const SizedBox(height: 16),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('使用模糊本地查找'),
          value: _useFuzzy,
          onChanged: (value) => setState(() => _useFuzzy = value),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('使用情感標註'),
          value: _useSentiment,
          onChanged: (value) => setState(() => _useSentiment = value),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('包含 LM（Marian）路線'),
          value: _useLm,
          onChanged: (value) => setState(() => _useLm = value),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('允許簡體輸入'),
          value: _allowSimplified,
          onChanged: (value) => setState(() => _allowSimplified = value),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('進階搜尋使用 OpenAI'),
          value: _useOpenAiAdvanced,
          onChanged: (value) => setState(() => _useOpenAiAdvanced = value),
        ),
        if (_useOpenAiAdvanced)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: TextField(
              controller: _openAiApiKeyController,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'OpenAI API 金鑰',
                border: OutlineInputBorder(),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildHistoryTab() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            const Expanded(child: Text('翻譯紀錄', style: TextStyle(fontSize: 18))),
            OutlinedButton(
              onPressed: _isHistoryLoading ? null : _fetchHistory,
              child: Text(_isHistoryLoading ? '載入中...' : '重新整理'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (_historyError != null) Text(_historyError!),
        if (_historyEntries.isEmpty && !_isHistoryLoading)
          const Text('目前沒有翻譯紀錄。'),
        ..._historyEntries.map(
          (item) => Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.time, style: const TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 6),
                  Text('輸入: ${item.input}'),
                  const SizedBox(height: 6),
                  Text('輸出: ${item.output}'),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildResultView(TranslationResponse result) {
    final scoreEntries = result.scores.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));

    final translationEntries = result.translations.entries
      .where((entry) => entry.key.toLowerCase() != 'deepl')
      .toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: double.infinity,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '來源與標籤',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 6),
                  Text('情感標籤: ${_bilingualLabel(result.sentiment, sentimentZhMap)}'),
                  Text(
                    '助語詞標籤: ${result.sfpDetails.isEmpty ? '（無）' : result.sfpDetails.map((item) => '${item.character}: ${_classifySfpMeaning(item.meaning)}').join('; ')}',
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '本地來源: ${result.localSourceLine.isEmpty ? '（沒有本地匹配）' : result.localSourceLine}',
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 10),
        SizedBox(
          width: double.infinity,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '已選翻譯',
                    style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFF59D),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: const Color(0xFFFBC02D)),
                    ),
                    child: Text(result.finalTranslation),
                  ),
                  const SizedBox(height: 8),
                  Text('已選 API: ${result.chosenApi}'),
                  Text('句型: ${result.sentenceType}'),
                  Text('情感: ${result.sentiment}'),
                  Text('助語詞數量: ${result.sfpCount}'),
                  if (result.replacementNotes.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text('粗口正規化: ${result.replacementNotes.join(', ')}'),
                  ],
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 10),
        SizedBox(
          width: double.infinity,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '輸入追蹤',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 6),
                  Text('原文: ${result.input}'),
                  Text('正規化: ${result.normalizedInput}'),
                  Text('查找方式: ${result.traceMethod}'),
                  Text('模糊分數（RapidFuzz WRatio, 0-100）: ${result.traceScore.toStringAsFixed(2)}'),
                  const Text('說明：分數越高越相似，85 分以上才會視為模糊命中。'),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 10),
        SizedBox(
          width: double.infinity,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '全部翻譯候選',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  ...translationEntries.map(
                    (entry) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text('${entry.key}: ${entry.value}'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 10),
        SizedBox(
          width: double.infinity,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '模型分數',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  ...scoreEntries.map(
                    (entry) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text('${entry.key}: ${entry.value.toStringAsFixed(3)}'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildAdvancedResultView(AdvancedSearchResponse result) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '進階改寫（Ollama）',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 6),
                Text(result.ollama.isEmpty ? '（沒有輸出）' : result.ollama),
                if (result.openai.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  const Text(
                    '進階改寫（OpenAI）',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 6),
                  Text(result.openai),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '本地最佳匹配',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                if (result.topMatches.isEmpty)
                  const Text('沒有符合所選標籤的本地資料。'),
                ...result.topMatches.map(
                  (item) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('中文: ${item.cantoneseText}'),
                        Text('英文: ${item.englishTranslation}'),
                        Text('情感: ${_zhListLabel(item.emotion, emotionZhMap)}'),
                        Text('態度: ${_zhListLabel(item.attitude, attitudeZhMap)}'),
                        Text('關係: ${_zhListLabel(item.relationship, relationshipZhMap)}'),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class AdvancedSearchResponse {
  AdvancedSearchResponse({
    required this.ollama,
    required this.openai,
    required this.topMatches,
  });

  final String ollama;
  final String openai;
  final List<AdvancedLocalMatch> topMatches;

  factory AdvancedSearchResponse.fromJson(Map<String, dynamic> json) {
    final raw = (json['top_matches'] as List<dynamic>? ?? <dynamic>[])
        .map((e) => AdvancedLocalMatch.fromJson(e as Map<String, dynamic>))
        .toList();

    return AdvancedSearchResponse(
      ollama: json['ollama']?.toString() ?? '',
      openai: json['openai']?.toString() ?? '',
      topMatches: raw,
    );
  }
}

class AdvancedLocalMatch {
  AdvancedLocalMatch({
    required this.cantoneseText,
    required this.englishTranslation,
    required this.emotion,
    required this.attitude,
    required this.relationship,
  });

  final String cantoneseText;
  final String englishTranslation;
  final String emotion;
  final String attitude;
  final String relationship;

  factory AdvancedLocalMatch.fromJson(Map<String, dynamic> json) {
    return AdvancedLocalMatch(
      cantoneseText: json['cantonese_text']?.toString() ?? '',
      englishTranslation: json['english_translation']?.toString() ?? '',
      emotion: json['emotion']?.toString() ?? '',
      attitude: json['attitude']?.toString() ?? '',
      relationship: json['relationship']?.toString() ?? '',
    );
  }
}

class TranslationResponse {
  TranslationResponse({
    required this.input,
    required this.normalizedInput,
    required this.sentenceType,
    required this.sfpCount,
    required this.traceMethod,
    required this.traceScore,
    required this.sentiment,
    required this.translations,
    required this.chosenApi,
    required this.scores,
    required this.finalTranslation,
    required this.replacementNotes,
    required this.localSourceLine,
    required this.sfpDetails,
  });

  final String input;
  final String normalizedInput;
  final String sentenceType;
  final int sfpCount;
  final String traceMethod;
  final double traceScore;
  final String sentiment;
  final Map<String, String> translations;
  final String chosenApi;
  final Map<String, double> scores;
  final String finalTranslation;
  final List<String> replacementNotes;
  final String localSourceLine;
  final List<SfpDetail> sfpDetails;

  factory TranslationResponse.fromJson(Map<String, dynamic> json) {
    final trace = (json['trace'] as Map<String, dynamic>?) ?? {};

    final translationsRaw = (json['translations'] as Map<String, dynamic>?) ?? {};
    final parsedTranslations = <String, String>{};
    for (final entry in translationsRaw.entries) {
      parsedTranslations[entry.key] = entry.value?.toString() ?? '';
    }

    final scoresRaw = (json['scores'] as Map<String, dynamic>?) ?? {};
    final parsedScores = <String, double>{};
    for (final entry in scoresRaw.entries) {
      final value = entry.value;
      if (value is num) {
        parsedScores[entry.key] = value.toDouble();
      } else {
        parsedScores[entry.key] =
            double.tryParse(value?.toString() ?? '') ?? 0.0;
      }
    }

    final replacementRaw = (json['replacement_notes'] as List<dynamic>?) ?? <dynamic>[];
    final replacementNotes =
      replacementRaw.map((e) => e.toString()).where((e) => e.trim().isNotEmpty).toList();

    final sfpRaw = (json['sfp_details'] as List<dynamic>?) ?? <dynamic>[];
    final sfpDetails = sfpRaw
      .whereType<Map<String, dynamic>>()
      .map((e) => SfpDetail.fromJson(e))
      .toList();

    return TranslationResponse(
      input: json['input']?.toString() ?? '',
      normalizedInput: json['normalized_input']?.toString() ?? '',
      sentenceType: json['sentence_type']?.toString() ?? '',
      sfpCount: (json['sfp_count'] as num?)?.toInt() ?? 0,
      traceMethod: trace['method']?.toString() ?? 'unknown',
      traceScore: (trace['score'] as num?)?.toDouble() ?? 0.0,
      sentiment: json['sentiment']?.toString() ?? 'neutral',
      translations: parsedTranslations,
      chosenApi: json['chosen_api']?.toString() ?? 'unknown',
      scores: parsedScores,
      finalTranslation: json['final_translation']?.toString() ?? '',
      replacementNotes: replacementNotes,
      localSourceLine: json['local_source_line']?.toString() ?? '',
      sfpDetails: sfpDetails,
    );
  }
}

class SfpDetail {
  SfpDetail({
    required this.character,
    required this.meaning,
    required this.jyutping,
    required this.engpinyin,
  });

  final String character;
  final String meaning;
  final String jyutping;
  final String engpinyin;

  factory SfpDetail.fromJson(Map<String, dynamic> json) {
    return SfpDetail(
      character: json['character']?.toString() ?? '',
      meaning: json['meaning']?.toString() ?? '',
      jyutping: json['jyutping']?.toString() ?? '',
      engpinyin: json['engpinyin']?.toString() ?? '',
    );
  }
}

class SfpEntry {
  SfpEntry({
    required this.character,
    required this.jyutping,
    required this.engpinyin,
    required this.meaning,
  });

  final String character;
  final String jyutping;
  final String engpinyin;
  final String meaning;

  factory SfpEntry.fromJson(Map<String, dynamic> json) {
    return SfpEntry(
      character: json['character']?.toString() ?? '',
      jyutping: json['jyutping']?.toString() ?? '',
      engpinyin: json['engpinyin']?.toString() ?? '',
      meaning: json['meaning']?.toString() ?? '',
    );
  }
}

class FoulEntry {
  FoulEntry({
    required this.canonical,
    required this.literal,
    required this.desired,
    required this.variations,
  });

  final String canonical;
  final String literal;
  final String desired;
  final List<String> variations;

  factory FoulEntry.fromJson(Map<String, dynamic> json) {
    final rawVars = json['variations'];
    final vars = <String>[];
    if (rawVars is List) {
      for (final v in rawVars) {
        final s = v?.toString() ?? '';
        if (s.isNotEmpty) {
          vars.add(s);
        }
      }
    }

    return FoulEntry(
      canonical: json['canonical']?.toString() ?? '',
      literal: json['literal']?.toString() ?? '',
      desired: json['desired']?.toString() ?? '',
      variations: vars,
    );
  }
}

class HistoryEntry {
  HistoryEntry({
    required this.input,
    required this.output,
    required this.time,
  });

  final String input;
  final String output;
  final String time;

  factory HistoryEntry.fromJson(Map<String, dynamic> json) {
    return HistoryEntry(
      input: json['input']?.toString() ?? '',
      output: json['output']?.toString() ?? '',
      time: json['time']?.toString() ?? '',
    );
  }
}
