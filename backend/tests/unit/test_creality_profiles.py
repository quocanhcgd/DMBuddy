from backend.app.api.routes.creality_profiles import PROFILE_ROOT, _catalog


def test_catalog_includes_k_series_machine_process_and_filament_profiles():
    catalog = _catalog()

    assert len(catalog["printer"]) > 0
    assert len(catalog["process"]) > 0
    assert len(catalog["filament"]) > 0

    k3 = next(profile for profile in catalog["printer"] if profile["name"] == "Creality K3")
    assert k3["printer"] == "K3"
    assert k3["inherits"] == "fdm_creality_common"
    assert k3["nozzles"] == ["0.4"]

    k2_processes = [profile for profile in catalog["process"] if (profile["printer"] or "").startswith("K2")]
    assert k2_processes
    assert all(not profile["printer"].endswith(("0.2", "0.4", "0.6", "0.8")) for profile in k2_processes)


def test_bundled_profile_source_license_and_creality_base_profiles_exist():
    assert (PROFILE_ROOT / "LICENSE.txt").is_file()
    assert (PROFILE_ROOT / "machine" / "fdm_creality_common.json").is_file()
    assert (PROFILE_ROOT / "process" / "fdm_process_creality_common.json").is_file()
    assert (PROFILE_ROOT / "filament" / "fdm_filament_pla.json").is_file()
