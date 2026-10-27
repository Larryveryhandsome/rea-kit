"""Shared, I/O-free area/type vocabulary for imports and matching."""
PROPERTY_TYPES = ("電梯大樓", "華廈", "公寓", "透天", "別墅", "套房", "店面", "辦公", "廠房", "土地", "農地", "車位")
CITIES = ("台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", "基隆市", "新竹市", "嘉義市",
          "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
          "台東縣", "澎湖縣", "金門縣", "連江縣")
_ALIASES = {"apartment": "公寓", "華夏": "華廈", "大樓": "電梯大樓", "住宅大樓": "電梯大樓",
            "透天厝": "透天", "商辦": "辦公", "office": "辦公", "land": "土地", "factory": "廠房",
            # 仲介平常的講法（2026-10-02 模擬整天操作時被擋下的）
            "大廈": "電梯大樓", "電梯": "電梯大樓", "電梯華廈": "華廈", "獨立套房": "套房", "分租套房": "套房",
            "小套房": "套房", "店鋪": "店面", "店舖": "店面", "辦公室": "辦公", "建地": "土地", "工廠": "廠房",
            "停車位": "車位"}


def canonical_type(value):
    text = str(value or "").strip().casefold()
    return _ALIASES.get(text, text)


def canonical_area(value):
    return "".join(str(value or "").replace("臺", "台").split()).casefold()


def area_matches(actual, requested):
    actual, requested = canonical_area(actual), canonical_area(requested)
    return bool(actual and requested) and (actual == requested or
           (requested in CITIES and actual.startswith(requested)))
