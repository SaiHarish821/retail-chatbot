def find_mismatches(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    stack = []
    lines = content.split('\n')
    
    in_string = False
    string_char = None
    escape = False
    in_comment = False
    comment_type = None # 'line' or 'block'
    
    pos = 0
    line_num = 1
    col_num = 1
    
    for char in content:
        if char == '\n':
            line_num += 1
            col_num = 1
        else:
            col_num += 1
            
        if escape:
            escape = False
            continue
            
        if in_comment:
            if comment_type == 'line' and char == '\n':
                in_comment = False
            elif comment_type == 'block' and content[pos:pos+2] == '*/':
                in_comment = False
                # Skip the '*' since we'll see '/' in next iteration
            pos += 1
            continue
            
        if in_string:
            if char == '\\':
                escape = True
            elif char == string_char:
                in_string = False
            pos += 1
            continue
            
        # Check comments
        if char == '/' and pos + 1 < len(content) and content[pos+1] == '/':
            in_comment = True
            comment_type = 'line'
            pos += 1
            continue
        if char == '/' and pos + 1 < len(content) and content[pos+1] == '*':
            in_comment = True
            comment_type = 'block'
            pos += 1
            continue
            
        # Check strings
        if char in ("'", '"', '`'):
            in_string = True
            string_char = char
            pos += 1
            continue
            
        # Check braces
        if char in ('(', '{', '['):
            stack.append((char, line_num, col_num))
        elif char in (')', '}', ']'):
            if not stack:
                print(f"Extra closing char '{char}' at line {line_num}, col {col_num}")
            else:
                top, t_line, t_col = stack.pop()
                if (top == '(' and char != ')') or (top == '{' and char != '}') or (top == '[' and char != ']'):
                    print(f"Mismatch: opened '{top}' at line {t_line}, col {t_col} but closed '{char}' at line {line_num}, col {col_num}")
                    
        pos += 1
        
    while stack:
        top, t_line, t_col = stack.pop()
        print(f"Unclosed '{top}' opened at line {t_line}, col {t_col}")

if __name__ == '__main__':
    find_mismatches('frontend/js/app.js')
