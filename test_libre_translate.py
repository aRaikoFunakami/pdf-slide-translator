from libretranslatepy import LibreTranslateAPI

lt = LibreTranslateAPI("http://127.0.0.1:5050/")
# (A) Languages
print(lt.languages())  # [{'code':'en','name':'English'}, ...]

# (B) Detect
print(lt.detect("こんにちは、世界。"))  # [{'language':'ja','confidence':...}]

# (C) Translate
print(lt.translate("こんにちは、世界。", "ja", "en"))