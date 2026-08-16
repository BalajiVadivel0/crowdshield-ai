import pytest

from app.models.announcement import AnnouncementPriority, AnnouncementChannel
from app.services.announcement_engine import DeterministicTemplateGenerator


@pytest.fixture
def generator():
    return DeterministicTemplateGenerator()


def test_english_generation(generator):
    announcements = generator.generate(
        event_id=1,
        zone_id=5,
        alert_type="CONGESTION_WARNING",
        priority=AnnouncementPriority.MEDIUM,
        target_languages=["en"]
    )
    
    assert len(announcements) == 1
    ann = announcements[0]
    assert ann.language == "en"
    assert "Zone 5" in ann.title
    assert "High traffic detected near Zone 5" in ann.message
    assert ann.priority == AnnouncementPriority.MEDIUM
    assert ann.channel == AnnouncementChannel.MOBILE_APP


def test_hindi_generation(generator):
    announcements = generator.generate(
        event_id=1,
        zone_id=10,
        alert_type="CRITICAL_ALERT",
        priority=AnnouncementPriority.CRITICAL,
        target_languages=["hi"]
    )
    
    assert len(announcements) == 1
    ann = announcements[0]
    assert ann.language == "hi"
    assert "ज़ोन 10 में सुरक्षा खतरा" in ann.title
    assert ann.priority == AnnouncementPriority.CRITICAL
    assert ann.channel == AnnouncementChannel.PUBLIC_PA


def test_multilingual_generation(generator):
    announcements = generator.generate(
        event_id=1,
        zone_id=2,
        alert_type="ROUTE_CHANGE",
        priority=AnnouncementPriority.LOW,
        target_languages=["en", "hi"]
    )
    
    assert len(announcements) == 2
    langs = [a.language for a in announcements]
    assert "en" in langs
    assert "hi" in langs


def test_unsupported_language_fallback(generator):
    # Requesting Spanish "es" should fallback to English "en" templates
    announcements = generator.generate(
        event_id=1,
        zone_id=3,
        alert_type="CONGESTION_WARNING",
        priority=AnnouncementPriority.MEDIUM,
        target_languages=["es"]
    )
    
    assert len(announcements) == 1
    ann = announcements[0]
    assert ann.language == "en"
    assert "High traffic" in ann.message


def test_deterministic_output(generator):
    # Verify exact same input yields exact same output string
    out1 = generator.generate(1, 1, "ROUTE_CHANGE", AnnouncementPriority.LOW, ["en"])[0]
    out2 = generator.generate(1, 1, "ROUTE_CHANGE", AnnouncementPriority.LOW, ["en"])[0]
    
    assert out1.title == out2.title
    assert out1.message == out2.message


def test_no_dangerous_wording(generator):
    # Extract all possible messages
    all_messages = []
    for lang, templates in generator.TEMPLATES.items():
        for k, template_dict in templates.items():
            all_messages.append(template_dict["message"].lower())
            
    dangerous_words = ["panic", "stampede", "run", "death", "die"]
    
    for msg in all_messages:
        for word in dangerous_words:
            assert word not in msg, f"Found dangerous word '{word}' in message: {msg}"
