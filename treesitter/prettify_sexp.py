import re

def prettify_sexp(sexp):
    # 1. 移除多餘的換行與重複空白，轉成單行以便處理
    sexp = re.sub(r'\s+', ' ', sexp.strip())
    
    result = []
    indent = 0
    i = 0
    
    while i < len(sexp):
        char = sexp[i]
        
        if char == '(':
            # 遇到左括號，換行並增加縮排
            result.append('\n' + '  ' * indent + '(')
            indent += 1
        elif char == ')':
            # 遇到右括號，減少縮排並補回括號
            indent -= 1
            result.append(')')
        else:
            # 內容（如 identifier, method_declaration 等）
            result.append(char)
        
        i += 1
    
    # 清理開頭可能產生的空行並回傳
    return "".join(result).strip()