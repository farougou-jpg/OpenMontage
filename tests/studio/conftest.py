"""Fixtures du studio : voix Piper réelle (locale) et voix « à audio figé » pour l'équivalence V2."""

from __future__ import annotations

import pytest

from lib.studio.narration.synth import MODEL


class CachedVoice:
    """Voix Piper réelle dont chaque phrase n'est synthétisée qu'une fois.

    Piper n'est pas déterministe : pour comparer octet par octet deux chaînes de
    traitement, on leur fournit exactement le même audio brut par texte.
    """

    def __init__(self, real) -> None:
        self._real = real
        self.config = real.config
        self._cache: dict[str, list] = {}
        self.synth_calls = 0

    def synthesize(self, text, syn_config=None):
        if text not in self._cache:
            self.synth_calls += 1
            self._cache[text] = list(self._real.synthesize(text, syn_config=syn_config))
        return list(self._cache[text])

    def phonemize(self, text):
        return self._real.phonemize(text)


def snapshot_projects() -> dict[str, str]:
    """Chemin relatif → SHA-256 de chaque fichier du vrai dossier `projects/`."""
    import hashlib
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "projects"
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            snap[p.relative_to(root).as_posix()] = h.hexdigest()
    return snap


@pytest.fixture(scope="session", autouse=True)
def projects_snapshot_before_studio_tests():
    """Instantané de `projects/` pris au démarrage des tests du studio, AVANT le premier test.

    `test_zz_no_project_events.py` (exécuté en dernier) le compare à l'état final :
    toute création, modification ou suppression dans `projects/` par un test est
    détectée, sans confondre les vrais projets du studio avec des écritures de test.
    """
    return snapshot_projects()


@pytest.fixture(autouse=True)
def isolated_project_events(tmp_path_factory, monkeypatch):
    """Isole le journal d'événements du socle (lib/events.py) pendant les tests du studio.

    Le socle rattache tout chemin situé sous `projects/` à un projet réel et y ajoute
    `events.jsonl` — y compris quand un test vérifie qu'une zone protégée
    (`projects/demos/...`) est refusée. La racine des projets du journal est donc
    redirigée vers un dossier temporaire isolé : aucun événement de test n'est écrit
    dans les vrais projets.
    """
    import lib.events
    root = tmp_path_factory.mktemp("evenements_projets")
    monkeypatch.setattr(lib.events, "PROJECTS_DIR", root)
    return root


@pytest.fixture(scope="session")
def piper_voice():
    if not MODEL.is_file():
        pytest.skip(f"voix Piper absente : {MODEL}")
    from lib.studio.narration.synth import load_voice
    return load_voice()


@pytest.fixture(scope="session")
def cached_voice(piper_voice):
    return CachedVoice(piper_voice)
