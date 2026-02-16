import httpx
from .base import BaseAdapter, Prospect


# Curated list of active coding bootcamps with contact info research targets
BOOTCAMPS = [
    {
        "name": "General Assembly",
        "url": "https://generalassemb.ly",
        "programs": ["Software Engineering", "Data Science", "UX Design"],
        "locations": "Global (remote + 20 cities)",
        "size": "35,000+ graduates",
        "contact_role": "Director of Student Outcomes",
        "contact_search": "General Assembly Director Student Outcomes OR Career Services",
        "pitch_angle": "accountability during immersive + portfolio proof after graduation",
    },
    {
        "name": "Flatiron School",
        "url": "https://flatironschool.com",
        "programs": ["Software Engineering", "Data Science", "Cybersecurity", "Product Design"],
        "locations": "Remote + NYC, Denver, DC, Seattle",
        "size": "10,000+ graduates",
        "contact_role": "VP of Education / Career Services Lead",
        "contact_search": "Flatiron School VP Education OR Career Services",
        "pitch_angle": "students document their learning journey as proof for employers",
    },
    {
        "name": "Hack Reactor (Galvanize)",
        "url": "https://www.hackreactor.com",
        "programs": ["Software Engineering Immersive"],
        "locations": "Remote + Austin, SF",
        "size": "15,000+ graduates",
        "contact_role": "Head of Curriculum / Career Outcomes",
        "contact_search": "Hack Reactor Head Curriculum OR Outcomes",
        "pitch_angle": "verifiable coding hours during intensive 12-week program",
    },
    {
        "name": "App Academy",
        "url": "https://www.appacademy.io",
        "programs": ["Full-Stack Web Development"],
        "locations": "Remote + NYC, SF",
        "size": "8,000+ graduates",
        "contact_role": "Director of Career Services",
        "contact_search": "App Academy Director Career Services",
        "pitch_angle": "income share model means outcomes matter — screen history proves job-readiness",
    },
    {
        "name": "Springboard",
        "url": "https://www.springboard.com",
        "programs": ["Software Engineering", "Data Science", "ML Engineering", "UX Design", "Cybersecurity"],
        "locations": "Fully Remote",
        "size": "20,000+ students",
        "contact_role": "VP of Learning / Mentor Program Lead",
        "contact_search": "Springboard VP Learning OR Mentor Program",
        "pitch_angle": "mentor-guided learning — screen history shows mentors exactly where students struggle",
    },
    {
        "name": "Codecademy (Skillsoft)",
        "url": "https://www.codecademy.com",
        "programs": ["Full-Stack Engineer", "Data Scientist", "Computer Science"],
        "locations": "Fully Remote",
        "size": "50M+ users, career path cohorts ~5,000/year",
        "contact_role": "Head of Enterprise / B2B Partnerships",
        "contact_search": "Codecademy Head Enterprise OR Partnerships",
        "pitch_angle": "Pro members completing career paths get verifiable proof beyond certificates",
    },
    {
        "name": "Lambda School / BloomTech",
        "url": "https://www.bloomtech.com",
        "programs": ["Full-Stack Web", "Data Science", "Backend"],
        "locations": "Fully Remote",
        "size": "3,000+ graduates",
        "contact_role": "Head of Student Experience",
        "contact_search": "BloomTech Head Student Experience OR Outcomes",
        "pitch_angle": "ISA model — employers need trust in graduate quality, screen history provides it",
    },
    {
        "name": "Thinkful (Chegg Skills)",
        "url": "https://www.thinkful.com",
        "programs": ["Software Engineering", "Data Science", "Data Analytics", "UX/UI Design"],
        "locations": "Fully Remote",
        "size": "10,000+ graduates",
        "contact_role": "Director of Student Success",
        "contact_search": "Thinkful Director Student Success",
        "pitch_angle": "1-on-1 mentoring sessions documented for both student and mentor review",
    },
    {
        "name": "Le Wagon",
        "url": "https://www.lewagon.com",
        "programs": ["Web Development", "Data Science", "Data Analytics"],
        "locations": "45+ cities globally (Berlin, London, Tokyo, etc.)",
        "size": "25,000+ alumni",
        "contact_role": "Global Head of Education / City Manager",
        "contact_search": "Le Wagon Head Education OR Global Manager",
        "pitch_angle": "international bootcamp — screen history works in any language/country as proof",
    },
    {
        "name": "Ironhack",
        "url": "https://www.ironhack.com",
        "programs": ["Web Development", "UX/UI Design", "Data Analytics", "Cybersecurity"],
        "locations": "12 cities (Madrid, Barcelona, Miami, Berlin, etc.)",
        "size": "15,000+ alumni",
        "contact_role": "Head of Outcomes / Career Services Director",
        "contact_search": "Ironhack Head Outcomes OR Career Services",
        "pitch_angle": "European market where bootcamp credentials face even more skepticism from employers",
    },
    {
        "name": "Fullstack Academy",
        "url": "https://www.fullstackacademy.com",
        "programs": ["Software Engineering", "Cybersecurity", "Data Analytics"],
        "locations": "Remote + NYC",
        "size": "5,000+ graduates",
        "contact_role": "VP of Education / Career Success Lead",
        "contact_search": "Fullstack Academy VP Education OR Career",
        "pitch_angle": "Grace Hopper program for women — screen history addresses bias by showing pure work quality",
    },
    {
        "name": "Coding Dojo",
        "url": "https://www.codingdojo.com",
        "programs": ["Full-Stack Development (3 stacks)", "Data Science"],
        "locations": "Remote + Bellevue, Silicon Valley",
        "size": "12,000+ graduates",
        "contact_role": "Director of Career Services",
        "contact_search": "Coding Dojo Director Career Services",
        "pitch_angle": "teaches 3 full stacks — screen history proves proficiency across all three",
    },
    {
        "name": "Turing School",
        "url": "https://turing.edu",
        "programs": ["Front-End Engineering", "Back-End Engineering", "Launch (beginner)"],
        "locations": "Fully Remote (Denver-based)",
        "size": "3,000+ graduates",
        "contact_role": "Director of Professional Development",
        "contact_search": "Turing School Director Professional Development",
        "pitch_angle": "nonprofit mission-driven — screen history aligns with transparency and equity values",
    },
    {
        "name": "Nucamp",
        "url": "https://www.nucamp.co",
        "programs": ["Web Development", "Full Stack", "Back End with Python/SQL", "Cybersecurity"],
        "locations": "Fully Remote",
        "size": "affordable ($2,000) — high volume, 10,000+ students",
        "contact_role": "Head of Partnerships / Academic Director",
        "contact_search": "Nucamp Head Partnerships OR Academic Director",
        "pitch_angle": "most affordable major bootcamp — free tool adds premium value at no cost to students",
    },
    {
        "name": "Codesmith",
        "url": "https://www.codesmith.io",
        "programs": ["Software Engineering Immersive"],
        "locations": "Remote + LA, NYC",
        "size": "2,500+ graduates, highly selective",
        "contact_role": "Head of Outcomes / Admissions Lead",
        "contact_search": "Codesmith Head Outcomes OR Admissions",
        "pitch_angle": "elite positioning — screen history proves the caliber matches the brand",
    },
    {
        "name": "Tech Elevator",
        "url": "https://www.techelevator.com",
        "programs": ["Java/C# Web Development"],
        "locations": "Remote + Cleveland, Columbus, Cincinnati, Pittsburgh, etc.",
        "size": "5,000+ graduates",
        "contact_role": "VP of Pathway Programs / Employer Relations",
        "contact_search": "Tech Elevator VP Pathway Programs OR Employer Relations",
        "pitch_angle": "strong employer pipeline — screen history makes graduates more placeable",
    },
    {
        "name": "Makers Academy",
        "url": "https://makers.tech",
        "programs": ["Software Development", "DevOps", "Cloud Engineering"],
        "locations": "London + Remote (UK)",
        "size": "3,000+ graduates",
        "contact_role": "Head of Education / Employer Partnerships",
        "contact_search": "Makers Academy Head Education OR Employer Partnerships",
        "pitch_angle": "UK market — screen history provides objective evidence for UK employers skeptical of bootcamps",
    },
    {
        "name": "4Geeks Academy",
        "url": "https://4geeksacademy.com",
        "programs": ["Full-Stack Development", "Data Science & ML"],
        "locations": "20+ locations (US, Latin America, Europe)",
        "size": "5,000+ graduates, lifetime career support",
        "contact_role": "Head of Career Support / Regional Director",
        "contact_search": "4Geeks Academy Head Career Support",
        "pitch_angle": "lifetime career support commitment — screen history is a permanent credential students keep forever",
    },
    {
        "name": "Microverse",
        "url": "https://www.microverse.org",
        "programs": ["Full-Stack Web Development"],
        "locations": "Fully Remote (global, focus on developing countries)",
        "size": "5,000+ students from 100+ countries",
        "contact_role": "Head of Curriculum / Partnerships Lead",
        "contact_search": "Microverse Head Curriculum OR Partnerships",
        "pitch_angle": "ISA model for global students — screen history proves competence regardless of country/credential",
    },
    {
        "name": "Scrimba",
        "url": "https://scrimba.com",
        "programs": ["Frontend Developer Career Path", "AI Engineer Path"],
        "locations": "Fully Remote (interactive screencasts)",
        "size": "1M+ users, bootcamp cohorts ~2,000/year",
        "contact_role": "CEO / Head of Community",
        "contact_search": "Scrimba CEO Per Harald Borgen OR Head Community",
        "pitch_angle": "already screencast-native — screen history is a natural extension of interactive coding",
    },
]


class BootcampAdapter(BaseAdapter):
    name = "bootcamps"
    description = "Coding bootcamps to offer free Memex access for students — accountability + portfolio proof"
    icon = "bootcamp"
    categories = ["Education", "Bootcamp Partnerships"]

    def get_config_schema(self):
        return {
            "include_all": {
                "type": "boolean",
                "label": "Include all bootcamps",
                "default": True,
            },
        }

    async def fetch(self, config: dict) -> list[Prospect]:
        prospects = []
        for bc in BOOTCAMPS:
            signals = ["bootcamp_org", "education_partner"]
            if "remote" in bc["locations"].lower():
                signals.append("remote_program")
            if "global" in bc["locations"].lower() or "cities" in bc["locations"].lower():
                signals.append("multi_location")
            if "ISA" in bc.get("pitch_angle", "") or "income share" in bc.get("pitch_angle", "").lower():
                signals.append("isa_model")

            prospects.append(Prospect(
                source="bootcamps",
                username=bc["name"].lower().replace(" ", "-"),
                display_name=bc["name"],
                profile_url=bc["url"],
                bio=f"{', '.join(bc['programs'])}. {bc['locations']}. {bc['size']}.",
                category="Bootcamp Partnership",
                signals=signals,
                raw_data={
                    "programs": bc["programs"],
                    "locations": bc["locations"],
                    "size": bc["size"],
                    "contact_role": bc["contact_role"],
                    "contact_search": bc["contact_search"],
                    "pitch_angle": bc["pitch_angle"],
                },
            ))
        return prospects
