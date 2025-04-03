from datetime import datetime


def log(*args, **kwargs) -> None:
    """
    Add datetime to print() for logs.
    """
    error = kwargs.pop("error", False)
    print( # can replace this with a different logging system
        f"[{datetime.now().date().strftime('%Y-%m-%d')},",
        f"{datetime.now().strftime('%H:%M:%S')}]", 
        ("[ERROR]" if error else "[INFO]"),
        "-",
        *args,
        **kwargs
    ) # [2025-3-1, 7:11:30] - Hello world!

def esc_md(text: str) -> str:
    """
    Escape markdown.
    """
    escape_chars = ['*', '_', '~', '`', '|', '>', '[', ']', '(', ')', '#', '-', '+', '.']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}') # e.g. replace * with \*
    return text