# src/core/models.py
from django.db import models

class ResumeProfile(models.Model):
    name = models.CharField(max_length=100, default="Chloe Koo")
    title = models.CharField(max_length=200, default="Supply Chain Transformation & Automation Specialist | Practical Python Problem Solver")
    location = models.CharField(max_length=100, default="Malaysia, Kuala Lumpur")
    phone = models.CharField(max_length=50, default="+60 17-638 7638")
    email = models.EmailField(default="kwanyee.koo@gmail.com")

    professional_profile = models.TextField(
        default="A supply chain enthusiast and self-taught developer specializing in bridging the gap between complex business operations and technical automation..."
    )
    manifesto_intro = models.TextField(
        default="I am not a commercial software engineer by trade; I am an operations specialist who mastered Python as a strategic tool to eliminate inefficiency..."
    )
    manifesto_reason = models.TextField(
        default="After successfully transforming logistics operations and automating myself out of daily repetitive tasks, I am seeking to exit my current comfort zone..."
    )

    # --- New Education Fields ---
    edu_title = models.CharField(max_length=200, default="Academic Background in Accounting & Finance")
    edu_subtitle = models.CharField(max_length=200, default="Completed 6 months of Foundation and 2 years of Professional Degree coursework.")
    edu_quote = models.TextField(
        default="\"Pivoted from traditional academia to pursue a high-intensity, practice-based self-driven learning path. This background provided a rigorous foundation in financial logic and data integrity. I do not carry a formal degree, but I carry a portfolio of solved problems and live systems. I define my value not by credentials, but by my capability to learn rapidly and deliver tangible business results.\""
    )

    def __str__(self):
        return f"Resume Profile: {self.name}"

class Experience(models.Model):
    profile = models.ForeignKey(ResumeProfile, related_name='experiences', on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    date_range = models.CharField(max_length=100)
    company = models.CharField(max_length=200)
    is_current = models.BooleanField(default=False)
    bullets = models.TextField(help_text="Separate bullets with a newline")
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']

    def get_bullets(self):
        """Helper to split the text block into individual bullet points for the template"""
        return [b.strip() for b in self.bullets.strip().split('\n') if b.strip()]

class Competency(models.Model):
    profile = models.ForeignKey(ResumeProfile, related_name='competencies', on_delete=models.CASCADE)
    icon = models.CharField(max_length=50) # e.g., 'bi-rocket-takeoff-fill'
    title = models.CharField(max_length=100)
    description = models.TextField()
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']
