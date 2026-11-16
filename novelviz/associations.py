"""Single-request asset ID association, with local/manual alternatives."""

import copy


class AssociationMixin:
    def association_mode(self):
        return self.store.settings(self.account).get("asset_association_mode", "ai")

    def association_index(self):
        return [
            dict(
                id=a["id"],
                name=a["name"],
                kind=a["kind"],
                aliases=a.get("aliases", []),
                identity=(
                    a.get("details", {}).get("background", "") or a.get("notes", "")
                )[:100],
            )
            for a in self.project.assets()
        ]

    def sync_scene_link_draft(self, scene):
        draft = self.project.config.get("split_drafts", {}).get(self.segment, {})
        for row in draft.get("rows", []):
            if row.get("id") == scene:
                row["required_assets"] = self.project.requirements(scene)

    def resolve_scene_links(self, rows, job):
        mode = job.get("association_mode", self.association_mode())
        assets = {a["id"]: a for a in self.project.assets()}
        allowed = {a["id"] for a in job.get("association_index", list(assets.values()))}
        old = self.project.scenes(self.segment)
        for row in rows:
            row.pop("required_assets", None)
            supplied = "asset_ids" in row
            ids = row.pop("asset_ids", [])
            if mode == "ai":
                if not isinstance(ids, list) or any(
                    not isinstance(i, str) or i not in assets or i not in allowed
                    for i in ids
                ):
                    row["association_note"] = (
                        "模型返回了无效资产ID，已排除无效关联；请核对并手工补充。"
                    )
                    ids = (
                        [
                            i
                            for i in ids
                            if isinstance(i, str) and i in assets and i in allowed
                        ]
                        if isinstance(ids, list)
                        else []
                    )
                elif not supplied and allowed:
                    row["association_note"] = (
                        "模型未返回资产关联，请核对并手工补充，或选用本地匹配。"
                    )
            overlap = [
                r
                for r in old
                if r["start_paragraph"] <= row["end_paragraph"]
                and r["end_paragraph"] >= row["start_paragraph"]
            ]
            exact = [
                r
                for r in overlap
                if r["start_paragraph"] == row["start_paragraph"]
                and r["end_paragraph"] == row["end_paragraph"]
            ]
            if len(exact) == 1:
                row["id"] = exact[0]["id"]
            manual = []
            excluded = set()
            for previous in overlap:
                excluded.update(
                    self.project.config.get("asset_match_exclusions", {}).get(
                        previous["id"], []
                    )
                )
                for link in self.project.requirements(previous["id"]):
                    if (
                        not link.get("auto_asset_link")
                        and not link.get("ai_asset_link")
                        and not any(
                            v.get("asset_id") == link.get("asset_id") for v in manual
                        )
                    ):
                        manual.append(copy.deepcopy(link))
            linked = {r.get("asset_id") for r in manual}
            if mode == "ai":
                for identity in dict.fromkeys(ids):
                    if identity not in excluded and identity not in linked:
                        a = assets[identity]
                        manual.append(
                            dict(
                                asset_id=identity,
                                name=a["name"],
                                kind=a["kind"],
                                ai_asset_link=True,
                                auto_asset_link=True,
                            )
                        )
            row["required_assets"] = manual
            row["association_exclusions"] = sorted(excluded)
            row["association_mode"] = mode
