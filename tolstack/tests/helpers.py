"""Small model builders for tests."""

from tolstack.model import (
    Chain, Contact, Contributor, Feature, FunctionalCharacteristic, Normal, Project, StatisticalAssumption,
    ToleranceSpec,
)


def simple_stack(dims, *, lsl=None, usl=None, nominal=None, rule="none", k=3.0, dists=None, unit="mm"):
    """Chain of blocks: housing span H from F0 to Fn (+), blocks B1..Bm stacked from F0 with contacts.
    dims: list of (id, nominal, upper, lower); the first entry is the housing span, the rest are blocks.
    Output gap = H - sum(blocks), from the last block's right face to the housing right face."""
    p = Project(project_id="T", name="test", base_unit="mm",
                statistical_assumption=StatisticalAssumption(rule=rule, k=k))
    hid, hn, hu, hl = dims[0]
    p.features += [Feature(id="H_L", component="HSG"), Feature(id="H_R", component="HSG")]
    p.contributors.append(Contributor(id=hid, component="HSG", from_feature="H_L", to_feature="H_R", direction=1,
                                      tolerance=ToleranceSpec(nominal=hn, upper=hu, lower=hl, unit=unit)))
    prev = "H_L"
    for (bid, bn, bu, bl) in dims[1:]:
        p.features += [Feature(id=f"{bid}_L", component=bid), Feature(id=f"{bid}_R", component=bid)]
        p.contacts.append(Contact(id=f"K_{bid}", feature_a=prev, feature_b=f"{bid}_L", assumption="pushed left"))
        p.contributors.append(Contributor(id=bid, component=bid, from_feature=f"{bid}_L", to_feature=f"{bid}_R",
                                          direction=1, tolerance=ToleranceSpec(nominal=bn, upper=bu, lower=bl, unit=unit)))
        prev = f"{bid}_R"
    if dists:
        for cid, d in dists.items():
            next(c for c in p.contributors if c.id == cid).distribution = d
    p.characteristic = FunctionalCharacteristic(id="G", name="gap", type="axial_gap", start_feature=prev,
                                                end_feature="H_R", unit="mm", lsl=lsl, usl=usl,
                                                nominal_declared=nominal)
    order = [d[0] for d in reversed(dims[1:])] + [hid]
    p.chains = [Chain(id="A", contributor_ids=order)]
    return p


def normal(mu, sigma):
    return Normal(mu=mu, sigma=sigma)
