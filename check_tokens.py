import tokenize
with open(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py', 'rb') as f:
    tokens = list(tokenize.tokenize(f.readline))
    for tok in tokens:
        if tok.type == tokenize.ERRORTOKEN:
            print(f'ERROR TOKEN at line {tok.start[0]}: {tok.line}')
        if tok.type == tokenize.ENCODING:
            print(f'Encoding: {tok.string}')