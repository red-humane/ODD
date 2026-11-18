"""
Typing Sound Bit-Identical Regression Test
Asserts that the search typing sound produces the exact bit-for-bit identical WAV output.
"""
import hashlib
import odd_sound

# Frozen ground-truth reference hash
EXPECTED_SHA256 = "cc6812fde307cf0fe48ca738ef0a17f0ffa5db29a7732541726663309da90806"
EXPECTED_LEN = 1366

def test_typing_sound_bit_identical():
    wav_bytes = odd_sound._synth_type()
    assert len(wav_bytes) == EXPECTED_LEN, f"Expected length {EXPECTED_LEN}, got {len(wav_bytes)}"
    h = hashlib.sha256(wav_bytes).hexdigest()
    assert h == EXPECTED_SHA256, f"Typing sound hash mismatch!\nExpected: {EXPECTED_SHA256}\nGot:      {h}"
    print(f"-> PASS: Typing sound is bit-identical (len={len(wav_bytes)}, sha256={h[:16]}...)")

if __name__ == "__main__":
    test_typing_sound_bit_identical()
