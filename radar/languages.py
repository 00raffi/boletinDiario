"""Indicación ligera en/es; en casos ambiguos el modelo conserva el idioma del texto.

No usa inferencia adicional ni pretende identificar todos los idiomas.
"""
import re
from collections import Counter

_WORDS = {
    "en": {"the", "and", "of", "to", "in", "we", "our", "this", "with", "for", "that", "are", "is", "on", "by",
           "from", "which", "an", "as", "these", "results", "method", "paper"},
    "es": {"el", "la", "los", "las", "de", "del", "y", "en", "que", "se", "un", "una", "para", "por", "con",
           "este", "esta", "nuestro", "nuestra", "nuestros", "estas", "resultados", "método", "artículo"},
}


def text_language(text):
    words = Counter(re.findall(r"[^\W\d_]+", text.casefold()))
    scores = {language: sum(words[word] for word in markers) for language, markers in _WORDS.items()}
    best = max(scores, key=scores.get)
    other = "es" if best == "en" else "en"
    return best if scores[best] >= 3 and scores[best] >= scores[other] * 2 + 2 else None


def language_instruction(language):
    if language == "en":
        return "Write the scientific content in English. Do not translate it into Spanish."
    if language == "es":
        return "Escribe el contenido científico en español. No lo traduzcas al inglés."
    return "Conserva el idioma predominante del texto original; no lo traduzcas."
