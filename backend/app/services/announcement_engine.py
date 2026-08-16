from abc import ABC, abstractmethod
from typing import List, Dict

from app.models.announcement import Announcement, AnnouncementChannel, AnnouncementPriority


class BaseAnnouncementGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        event_id: int,
        zone_id: int,
        alert_type: str,
        priority: AnnouncementPriority,
        target_languages: List[str]
    ) -> List[Announcement]:
        """Generates multilingual announcements based on input context."""
        pass


class DeterministicTemplateGenerator(BaseAnnouncementGenerator):
    """
    MVP Implementation that maps intervention/alert context to 
    safe, deterministic string templates. 
    Prevents LLM hallucination and panic-inducing language.
    """

    TEMPLATES = {
        "en": {
            "CRITICAL_ALERT": {
                "title": "Safety Hazard in Zone {zone}",
                "message": "Please avoid Zone {zone}. Use alternate routes for your safety.",
            },
            "CONGESTION_WARNING": {
                "title": "High Traffic in Zone {zone}",
                "message": "High traffic detected near Zone {zone}. Please proceed calmly.",
            },
            "ROUTE_CHANGE": {
                "title": "Route Redirected",
                "message": "Route redirected near Zone {zone} for your safety. Follow the digital signs.",
            },
            "DEFAULT": {
                "title": "Public Announcement",
                "message": "Please be advised of safety measures near Zone {zone}.",
            }
        },
        "hi": {
            "CRITICAL_ALERT": {
                "title": "ज़ोन {zone} में सुरक्षा खतरा",
                "message": "कृपया ज़ोन {zone} से बचें। अपनी सुरक्षा के लिए वैकल्पिक मार्गों का उपयोग करें।",
            },
            "CONGESTION_WARNING": {
                "title": "ज़ोन {zone} में भारी ट्रैफ़िक",
                "message": "ज़ोन {zone} के पास भारी भीड़ का पता चला है। कृपया शांतिपूर्वक आगे बढ़ें।",
            },
            "ROUTE_CHANGE": {
                "title": "मार्ग परिवर्तन",
                "message": "आपकी सुरक्षा के लिए ज़ोन {zone} के पास मार्ग बदल दिया गया है। डिजिटल संकेतों का पालन करें।",
            },
            "DEFAULT": {
                "title": "सार्वजनिक घोषणा",
                "message": "कृपया ज़ोन {zone} के पास सुरक्षा उपायों से अवगत रहें।",
            }
        }
    }

    def generate(
        self,
        event_id: int,
        zone_id: int,
        alert_type: str,
        priority: AnnouncementPriority,
        target_languages: List[str]
    ) -> List[Announcement]:
        
        announcements = []

        for lang in target_languages:
            # Fallback to English if language not supported
            template_lang = lang if lang in self.TEMPLATES else "en"
            
            # Fallback to DEFAULT if alert_type not supported
            template_dict = self.TEMPLATES[template_lang].get(
                alert_type, self.TEMPLATES[template_lang]["DEFAULT"]
            )

            title = template_dict["title"].format(zone=zone_id)
            message = template_dict["message"].format(zone=zone_id)

            # Determine channel based on priority
            channel = AnnouncementChannel.MOBILE_APP
            if priority in [AnnouncementPriority.HIGH, AnnouncementPriority.CRITICAL]:
                channel = AnnouncementChannel.PUBLIC_PA

            ann = Announcement(
                event_id=event_id,
                zone_id=zone_id,
                language=template_lang, # Use the actual template lang (fallback is apparent in the data)
                title=title,
                message=message,
                priority=priority,
                channel=channel
            )
            announcements.append(ann)

        return announcements
