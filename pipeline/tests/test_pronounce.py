import unittest

from vrea.pronounce.normalize import load_lexicon, normalize_punctuation, prepare, variant_count
from vrea.pronounce.qa import canon, cer, rank, score_take, word_issues

LEX = load_lexicon()


class Normalize(unittest.TestCase):
    def test_punctuation(self):
        self.assertEqual(normalize_punctuation("उजाला — बस 'बिग बैंग' थी: ओम्"), "उजाला, बस बिग बैंग थी, ओम्")

    def test_respelling_keeps_unlisted_words(self):
        r = prepare("इतनी सूक्ष्म कि किसी ने", LEX)
        self.assertEqual(r.tts_text, "इतनी सूक्श्म कि किसी ने")

    def test_aum_letters(self):
        r = prepare("तीन स्वर होते हैं — अ, उ, और म। और म से शिव जी", LEX)
        self.assertIn("अ... उ... और म्।", r.tts_text)
        self.assertIn("म् से शिव", r.tts_text)

    def test_ma_inside_words_untouched(self):
        r = prepare("मैं हमेशा मम्मी से", LEX)
        self.assertEqual(r.tts_text, "मैं हमेशा मम्मी से")

    def test_variants(self):
        self.assertEqual(prepare("हर धड़कन में", LEX, variant=1).tts_text, "हर धड़्कन में")
        self.assertEqual(variant_count("हर धड़कन में", LEX), 2)
        self.assertEqual(prepare("ख़त्म", LEX, variant=5).tts_text, "खत्म")  # clamps to last
        # Sanskritized style: no colloquial ब्रम्हा- alternatives
        self.assertEqual(prepare("ब्रह्मांड", LEX, variant=5).tts_text, "ब्रह्मान्ड")

    def test_latin_loanword(self):
        self.assertEqual(prepare("Big Bang कहता है", LEX).tts_text, "बिग बैंग कहता है")

    def test_risk_flag_for_unknown_word(self):
        r = prepare("ऋतु बदली", LEX)
        self.assertIn(("ऋतु", "ri-vowel ऋ/ृ"), r.risks)


class QA(unittest.TestCase):
    def test_canon_ignores_inaudible_spelling(self):
        self.assertEqual(canon("ओम्। सूक्ष्म आवाज़ गूँज"), canon("ओम सूक्श्म आवाज गूंज"))

    def test_canon_ignores_asr_spelling_noise(self):
        # real IndicConformer outputs from the ep1 run vs the script
        for heard, script in [("चाँंद", "चाँद"), ("मेरे अन्ंदर", "मेरे अंदर"), ("पांँच तत्त्वों", "पाँच तत्वों"),
                              ("ब्रह््मांड", "ब्रह्मांड"), ("अ से ब्रह्माजी जिन्होंने", "अ से ब्रह्मा जी जिन्होंने")]:
            self.assertEqual(canon(heard), canon(script), heard)
        self.assertNotEqual(canon("पवित्र नी थी"), canon("पवित्र ध्वनि थी"))  # a real error stays visible

    def test_cer(self):
        self.assertEqual(cer("abc", "abc"), 0.0)
        self.assertAlmostEqual(cer("abcd", "abd"), 0.25)

    def test_word_issues_and_rank(self):
        script = "हर धड़कन में बजी हुई है"
        good = score_take("good.wav", script, "हर धड़कन में बजी हुई है", 1.6)
        bad = score_take("bad.wav", script, "हर धड़ाकन में बज हुई है", 1.6)
        self.assertEqual(good.word_issues, [])
        self.assertEqual([i["expected"] for i in word_issues(script, bad.transcript)], ["धडकन", "बजी"])
        self.assertEqual([t.path for t in rank([bad, good])], ["good.wav", "bad.wav"])

    def test_pace(self):
        slow = score_take("slow.wav", "हर धड़कन में", "हर धड़कन में", 5.0)
        self.assertFalse(slow.pace_ok)


if __name__ == "__main__":
    unittest.main()
