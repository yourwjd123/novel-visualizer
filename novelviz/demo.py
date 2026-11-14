"""Explicit offline demonstration. Images are supplied examples, not API results."""

from pathlib import Path
import shutil

from .storage import now, uid


def seed_visual_demo(store):
    a = store.accounts[0]
    if store.projects(a):
        return
    p = store.create_project(a, "青灯夜渡 · 离线演示")
    text = "\n\n".join(
        [
            "暮色沉入江面，细雨打湿了渡口的青石。沈青提着一盏旧铜灯，站在柳树下。",
            "“船还来吗？”她问。摆渡人把竹篙靠在船边，望了望雾里的对岸。",
            "“先别急。”摆渡人压低声音，从蓑衣里取出一封红蜡封口的信。",
            "他把信递到沈青面前。她伸手接过，指尖碰到了冰凉的蜡封。",
            "灯火轻轻一晃，照亮两人之间的雨丝。摆渡人没有再说话。",
            "沈青把信收进衣襟，转头望向江面。对岸依稀有一点灯光。",
            "雾里的旧埠只剩模糊的轮廓，渡船在水中轻轻摇晃。",
            "她握紧灯柄，沿着湿滑的石阶走向船头。",
        ]
    )
    sid = p.add_segment("第一章 · 雨夜渡口（虚构示例）", text)
    scenes = p.apply_scene_candidates(
        sid,
        [
            dict(
                title="雨夜候船",
                summary="沈青在渡口候船，询问摆渡人。",
                visual_moment="提灯的人物与雨夜渡口。",
                start_paragraph=1,
                end_paragraph=2,
            ),
            dict(
                title="渡口来信",
                summary="摆渡人将红蜡封信递给沈青。",
                visual_moment="两人交接信件，灯光照亮双手。",
                start_paragraph=3,
                end_paragraph=5,
            ),
            dict(
                title="遥望对岸",
                summary="沈青收信，望向旧埠并走向船头。",
                visual_moment="提灯的背影、渡船与江雾。",
                start_paragraph=6,
                end_paragraph=8,
            ),
        ],
    )
    samples = [
        (
            "沈青",
            "人物",
            "灰蓝布衣、低髻（演示补充设定）；原文未明确的细节可自行调整。",
            "shen.jpg",
        ),
        ("摆渡人", "人物", "蓑衣、斗笠；年长外观为演示补充设定。", "ferryman.jpg"),
        ("雨夜渡口", "场景", "木栈道、柳树与渡船。环境图为演示素材。", "pier.jpg"),
        (
            "旧铜灯",
            "道具",
            "铜质旧灯；当前图是演示插图的局部，细节需确认。",
            "lamp.jpg",
        ),
        ("红蜡封信", "道具", "红蜡封口；原文未描述信中文字。", None),
        ("对岸旧埠", "场景", "江雾中可见模糊轮廓；建筑细节保持未知。", None),
    ]
    assets = []
    for name, kind, description, image in samples:
        asset = p.save_asset(
            dict(
                name=name,
                kind=kind,
                description=description,
                source="用户自定",
                review="已确认" if image else "待确认",
                notes="内置虚构示例；图片由 AI 制作用于展示，未调用用户配置的服务。",
            )
        )
        if image:
            relative = p.save_asset_image(asset, Path(__file__).parent / "demo" / image)
            asset.update(
                image=relative,
                images=[
                    dict(
                        id=uid(),
                        path=relative,
                        source="内置演示素材（未联网生成）",
                        created=now(),
                    )
                ],
            )
            p.save_asset(asset)
        assets.append(asset)
    for scene in scenes:
        ids = (
            [0, 1, 2, 3]
            if scene == scenes[0]
            else [0, 1, 2, 3, 4]
            if scene == scenes[1]
            else [0, 2, 3, 5]
        )
        p.set_requirements(
            scene["id"],
            [
                dict(
                    name=assets[i]["name"],
                    kind=assets[i]["kind"],
                    asset_id=assets[i]["id"],
                )
                for i in ids
            ],
        )
    job_id = uid()
    dest = p.path / "05_生成任务" / job_id / "候选图片/内置示例.jpg"
    dest.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__).parent / "demo/scene.jpg", dest)
    p.save_job(
        dict(
            id=job_id,
            kind="内置示例图片（未调用 API）",
            created=now(),
            status="success",
            segment=sid,
            scene=scenes[1]["id"],
            results=[dest.relative_to(p.path).as_posix()],
            prompt="演示插图：雨夜渡口，沈青与摆渡人交接信件。",
            origin="offline_demo",
        )
    )
    p.config.setdefault("image_prompt_drafts", {})[scenes[1]["id"]] = (
        "古风写实画面。雨夜渡口，沈青与摆渡人交接红蜡封信，铜灯照亮两人的手；人物服装沿用已确认设定，远处渡船与江雾。不添加可读文字。"
    )
    p.config["rules"] = (
        "此项目为软件内置虚构示例；内置图片不是用户配置模型的真实调用结果。"
    )
    p.save_config()
    p.close()
