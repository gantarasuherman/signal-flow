class ProviderError(Exception):
    """Kesalahan umum dari data provider."""


class ProviderConfigError(ProviderError):
    """API key kosong/salah atau simbol tidak didukung."""


class ProviderUnavailableError(ProviderError):
    """Provider tidak bisa dihubungi setelah beberapa kali retry."""


class RateLimitError(ProviderError):
    """Kuota request per menit/hari habis."""


class NoDataError(ProviderError):
    """Provider tidak punya data untuk rentang yang diminta (mis. weekend)."""
