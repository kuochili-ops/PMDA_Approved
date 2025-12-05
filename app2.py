
from googletrans import Translator

# 建立翻譯器
translator = Translator()

# 要翻譯的日文成分名清單
japanese_names = [
    "ドロスピレノン",
    "イプタコパン塩酸塩水和物",
    "ファリシマブ（遺伝子組換え）",
    "RSウイルスの融合前安定化F糖タンパク質をコードするmRNA",
    "ベランタマブ マホドチン（遺伝子組換え）"
]

# 批次翻譯
translated = []
for name in japanese_names:
    result = translator.translate(name, src='ja', dest='en')
    translated.append(result.text)

# 顯示結果
for jp, en in zip(japanese_names, translated):
    print(f"{jp} → {en}")
