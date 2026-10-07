from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import torch


SCRIPT = (Path(__file__).resolve().parents[1] / "code/applications/experiments"
          / "dq_yolo_generative_pack.py")
SPEC = spec_from_file_location("dq_yolo_generative_pack", SCRIPT)
pack = module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


def test_clean_generators_are_reproducible_and_have_ood_tails():
    train = pack.sample_clean(17, "train")
    assert np.array_equal(train, pack.sample_clean(17, "train"))
    ood = pack.sample_clean(17, "ood")
    assert ood.shape == (pack.LENGTH,)
    assert np.isfinite(ood).all()


def test_injection_families_return_valid_event_intervals():
    base = pack.sample_clean(21)
    for family in pack.FAMILIES:
        changed, (start, end) = pack.inject(base, family, np.random.default_rng(2), 4)
        assert changed.shape == base.shape
        assert 0 <= start <= end < pack.LENGTH
        assert not np.array_equal(changed, base)


def test_vae_reconstructs_and_generates_fixed_window_shape():
    model = pack.ConvVAE()
    x = torch.zeros((3, pack.LENGTH))
    assert pack.vae_reconstruct(model, x).shape == x.shape
    generated = pack.vae_generate(model, 5, 9)
    assert generated.shape == (5, pack.LENGTH)
