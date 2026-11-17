import copy
import pytest
from novelviz.workflows import inspect_flow, validate_mapping, check_count


def graph(count=2):
    f = {
        "1": dict(
            class_type="PrimitiveStringMultiline", inputs=dict(value="old prompt")
        ),
        "2": dict(
            class_type="TextEncodeQwenImage21",
            inputs=dict(prompt=["1", 0], negative_prompt="negative"),
        ),
        "3": dict(class_type="Seed (rgthree)", inputs=dict(seed=-1)),
        "4": dict(
            class_type="KSampler",
            inputs=dict(seed=["3", 0], positive=["2", 0], negative=["2", 1]),
        ),
        "5": dict(class_type="SaveImage", inputs=dict(images=["4", 0])),
        "99": dict(class_type="PrimitiveStringMultiline", inputs=dict(value="unused")),
    }
    for i in range(1, count + 1):
        n = str(10 + i)
        f[n] = dict(class_type="LoadImage", inputs=dict(image=f"old-{i}.png"))
        f["2"]["inputs"]["images.image_" + str(i)] = [n, 0]
    return f


def test_local_mapping_traces_upstream_and_four_images():
    f = graph(4)
    original = copy.deepcopy(f)
    r = inspect_flow(f)
    assert r["mapping"] == dict(
        prompt=["1", "value"],
        seed=["3", "seed"],
        **{f"reference_{i}": [str(10 + i), "image"] for i in range(1, 5)},
    )
    assert r["reference_count"] == 4 and "99" not in r["active_nodes"]
    check_count(f, r["mapping"], 4)
    assert f == original


def test_count_mismatch_and_unmapped_old_image_are_rejected():
    f = graph(2)
    m = inspect_flow(f)["mapping"]
    with pytest.raises(ValueError, match="数量|参考图"):
        check_count(f, m, 1)
    del m["reference_2"]
    with pytest.raises(ValueError, match="旧图"):
        check_count(f, m, 1)


def test_ambiguous_positive_does_not_guess_and_negative_is_excluded():
    f = graph(0)
    f["6"] = dict(class_type="CLIPTextEncode", inputs=dict(text="other positive"))
    f["7"] = dict(
        class_type="ConditioningCombine",
        inputs=dict(conditioning_1=["2", 0], conditioning_2=["6", 0]),
    )
    f["4"]["inputs"]["positive"] = ["7", 0]
    r = inspect_flow(f)
    assert "prompt" not in r["mapping"] and len(r["candidates"]["prompt"]) == 2
    with pytest.raises(ValueError, match="字段不存在|有效输出"):
        validate_mapping(f, dict(prompt=["99", "value"]))


def test_duplicate_and_noncontiguous_reference_inputs_rejected():
    f = graph()
    m = inspect_flow(f)["mapping"]
    m["reference_2"] = m["reference_1"]
    with pytest.raises(ValueError, match="同一个输入"):
        validate_mapping(f, m)
    del m["reference_1"]
    with pytest.raises(ValueError, match="连续"):
        validate_mapping(f, m)


def test_editor_export_is_not_accepted():
    with pytest.raises(ValueError, match="API"):
        inspect_flow(dict(nodes=[], links=[]))


def test_custom_sampler_guider_and_random_noise_are_traced():
    f = graph(0)
    f["6"] = dict(class_type="BasicGuider", inputs=dict(conditioning=["2", 0]))
    f["7"] = dict(class_type="RandomNoise", inputs=dict(noise_seed=123))
    f["4"] = dict(
        class_type="SamplerCustomAdvanced", inputs=dict(guider=["6", 0], noise=["7", 0])
    )
    r = inspect_flow(f)
    assert r["mapping"]["prompt"] == ["1", "value"]
    assert r["mapping"]["seed"] == ["7", "noise_seed"]


def test_simple_latent_img2img_maps_one_source_image():
    f = graph(0)
    f["8"] = dict(class_type="LoadImage", inputs=dict(image="old.png"))
    f["9"] = dict(class_type="VAEEncode", inputs=dict(pixels=["8", 0]))
    f["4"]["inputs"]["latent_image"] = ["9", 0]
    r = inspect_flow(f)
    assert r["mapping"]["reference_1"] == ["8", "image"]
    check_count(f, r["mapping"], 1)
