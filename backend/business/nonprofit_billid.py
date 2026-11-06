"""Reference codes for the nonprofit module -- what a donor/member reads
back over the phone to staff, or that lands in a `?bill=`/`?donation=`
thank-you-page URL. Ported alphabet choice: excludes 0/O and 1/I, the two
pairs people misread most often when reading a code aloud."""
import secrets

_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
_LENGTH = 7


def new_reference_code():
    return ''.join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
