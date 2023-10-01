from dataclasses import dataclass

@dataclass
class Config:
    header_rows: int = 1
    extend_headers_top: int = 0
    extend_headers_bottom: int = 0
    skip: bool = False


CONFIGURATION = {
    2000: {
        'עיריות ומועצות מקומיות': Config(skip=True),
    },
    2001: {
        'עיריות ומועצות מקומיות': Config(skip=True),
    },
    2016: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=4, extend_headers_top=2),
    },
    2017: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5, extend_headers_top=2),
    },
    2018: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5),
    },
    2019: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5, extend_headers_top=1),
    },
    2020: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=5, extend_headers_top=1),
    },
    2021: {
        'נתונים פיזיים ונתוני אוכלוסייה': Config(header_rows=4, extend_headers_top=2),
        'נתוני תקציב': Config(header_rows=2, extend_headers_top=1),
        'נתוני הסקר החברתי': Config(skip=True),
    },
}