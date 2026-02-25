# src/core/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout
from django.utils.crypto import get_random_string
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.management import call_command
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, OuterRef, Subquery
from django.utils import timezone
from django.views.decorators.http import require_POST
from inventory.models import Product, InventorySnapshot
from production.models import ProductionOrder

from .models import ResumeProfile, Experience, Competency
from django.http import HttpResponse, HttpResponseForbidden
from django.template.loader import get_template
from xhtml2pdf import pisa
import io

def logout_view(request):
    """Logs out the user and redirects to the login page."""
    logout(request)
    return redirect('core:login')

def login_view(request):
    """
    Standard Login: Authenticates real users without modifying data.
    New users start with the current database state (empty if not seeded).
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # CRITICAL: Do NOT run seed_data here.
            # Real users manage their own data.
            return redirect('core:home')
    else:
        form = AuthenticationForm()

    context = {'form': form}

    # [Fix] Return Partial content for AJAX requests (e.g. Session Expiry Redirects)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'core/partials/login_content.html', context)

    return render(request, 'core/login.html', context)

def demo_login_view(request):
    """
    Demo Path: Logs in as 'guest_visitor' and forcefully resets/seeds data.
    """
    username = 'guest_visitor'
    user, created = User.objects.get_or_create(username=username)

    if created:
        user.set_password('demo_password_123')
        user.is_staff = False
        user.save()

    # Log the user in
    login(request, user)

    # Trigger Data Seeding immediately
    try:
        # This command clears the DB and repopulates it with Asia/Kuala_Lumpur aligned data
        call_command('seed_data')
        messages.success(request, "🚀 Welcome to the Live Demo! Data has been refreshed.")
    except Exception as e:
        messages.error(request, f"Demo initialization failed: {str(e)}")

    return redirect('core:home')

@login_required
def home(request):
    # 获取每个产品最新的库存快照
    latest_snapshot = InventorySnapshot.objects.filter(
        product=OuterRef('pk')
    ).order_by('-snapshot_date')

    # 在数据库层面计算当前库存和安全库存阈值
    products_with_stock = Product.objects.annotate(
        current_stock=Subquery(latest_snapshot.values('quantity_on_hand')[:1]),
        calculated_safety_stock=F('estimated_daily_usage') * F('safety_stock_days')
    )

    # 1. 总 SKU 数
    total_products = products_with_stock.count()

    # 2. 低库存预警 (当前库存 < 计算出的安全库存)
    low_stock_products = products_with_stock.filter(current_stock__lt=F('calculated_safety_stock'))
    low_stock_count = low_stock_products.count()

    # 3. 库存总值计算
    total_value = products_with_stock.aggregate(
        total=Sum(F('current_stock') * F('cost_price'))
    )['total'] or 0

    # 4. 获取最近30天的全库库存趋势 (用于图表)
    thirty_days_ago = timezone.now().date() - timezone.timedelta(days=30)
    history_data = InventorySnapshot.objects.filter(
        snapshot_date__gte=thirty_days_ago
    ).values('snapshot_date').annotate(
        total_value=Sum(F('quantity_on_hand') * F('product__cost_price'))
    ).order_by('snapshot_date')

    context = {
        'total_products': total_products,
        'low_stock_count': low_stock_count,
        'total_inventory_value': f"RM {total_value / 1000000:.2f}M" if total_value >= 1000000 else f"RM {total_value:,.2f}",
        'pending_pos': ProductionOrder.objects.filter(status='PENDING').count(),
        'urgent_items': low_stock_products[:5],
        # [CHANGED] Pass 'total_value' and ensure it handles None/Decimal conversion
        'chart_labels': [d['snapshot_date'].strftime('%Y-%m-%d') for d in history_data],
        'chart_values': [float(d['total_value'] or 0) for d in history_data],
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'core/partials/dashboard_content.html', context)

    return render(request, 'core/dashboard.html', context)




@login_required
@require_POST
def reset_demo_data(request):
    """
    Manual reset button (optional usage within the app)
    """
    try:
        call_command('seed_data')
        messages.success(request, "♻️ Data reset successfully.")
    except Exception as e:
        messages.error(request, f"Reset failed: {str(e)}")

    return redirect(request.META.get('HTTP_REFERER', 'core:home'))


def resume_view(request):
    resume, created = ResumeProfile.objects.get_or_create(id=1)

    # --- Auto-Seed Data if Empty (To preserve your exact hardcoded text automatically) ---
    if resume.experiences.count() == 0:
        Experience.objects.create(profile=resume, title="Warehouse Manager", date_range="Oct 2019 - Present", company="Logistics & Operations Management", is_current=True, bullets="Operational Transformation : Directed end-to-end logistics, transitioning from manual tracking to self-developed digital tools to ensure inventory integrity.\nAutomation Design : Engineered cross-departmental workflows with built-in \"self-supervision\" mechanisms to prevent critical errors in procurement and fulfillment.\nTechnical Resilience : Leveraged Python to build micro-services that bridge gaps in standard operational procedures, ensuring agility in high-pressure environments.", order=1)
        Experience.objects.create(profile=resume, title="Assistant Leasing Manager", date_range="Aug 2017 - Sept 2019", company="Avenue Bangi Management Sdn Bhd", is_current=False, bullets="Analyzed target markets to develop marketing strategies and coordinated complex tenant move-in/out logistics.", order=2)
        Experience.objects.create(profile=resume, title="Assistant Manager (Event & Promotion)", date_range="March 2017 - July 2017", company="Aivoria Group Sdn Bhd", is_current=False, bullets="Managed logistics for goods and fixtures; troubleshot and integrated company POS systems for events.", order=3)
        Experience.objects.create(profile=resume, title="Interior Fit-Out & Real Estate Executive", date_range="Dec 2015 - Feb 2017", company="Aivoria Group Sdn Bhd", is_current=False, bullets="Ensured M&E and interior design compliance with government regulations; managed company real estate assets.", order=4)
        Experience.objects.create(profile=resume, title="Team Manager / Senior Real Estate Negotiator", date_range="Oct 2010 - Jun 2015", company="Oriental Realty / Global Link Properties Sdn Bhd", is_current=False, bullets="Led recruitment and training, significantly increasing team sales revenue through data-backed performance coaching.", order=5)

    if resume.competencies.count() == 0:
        Competency.objects.create(profile=resume, icon="bi-rocket-takeoff-fill", title="Self-Driven Tech", description="Using Python & Django not for theory, but to build tools that solve real-world business inefficiencies through rapid SaaS development.", order=1)
        Competency.objects.create(profile=resume, icon="bi-graph-up-arrow", title="Autodidactic Growth", description="Proven ability to learn complex skills (Coding, 3D Design, Trading) from scratch without formal instruction.", order=2)
        Competency.objects.create(profile=resume, icon="bi-palette-fill", title="Learning Capability", description="Self-taught SketchUp for roadshow space planning and residential interior design (for my own house)", order=3)
        Competency.objects.create(profile=resume, icon="bi-shield-lock-fill", title="Operational Resilience", description="Expertise in building \"micro-solutions\" that strengthen the \"last mile\" of supply chain execution.", order=4)

    context = {'resume': resume}

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'core/partials/resume_content.html', context)
    return render(request, 'core/resume.html', context)


@login_required
@require_POST
def edit_resume(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("You do not have permission to edit the resume.")

    resume, _ = ResumeProfile.objects.get_or_create(id=1)

    # Update Basic & Manifesto Fields
    resume.name = request.POST.get('name', resume.name)
    resume.title = request.POST.get('title', resume.title)
    resume.location = request.POST.get('location', resume.location)
    resume.phone = request.POST.get('phone', resume.phone)
    resume.email = request.POST.get('email', resume.email)
    resume.professional_profile = request.POST.get('professional_profile', resume.professional_profile)
    resume.manifesto_intro = request.POST.get('manifesto_intro', resume.manifesto_intro)
    resume.manifesto_reason = request.POST.get('manifesto_reason', resume.manifesto_reason)

    # Update Education Fields
    resume.edu_title = request.POST.get('edu_title', resume.edu_title)
    resume.edu_subtitle = request.POST.get('edu_subtitle', resume.edu_subtitle)
    resume.edu_quote = request.POST.get('edu_quote', resume.edu_quote)
    resume.save()

    # Update Experiences
    for exp in resume.experiences.all():
        exp.title = request.POST.get(f'exp_title_{exp.id}', exp.title)
        exp.date_range = request.POST.get(f'exp_date_{exp.id}', exp.date_range)
        exp.company = request.POST.get(f'exp_company_{exp.id}', exp.company)
        exp.bullets = request.POST.get(f'exp_bullets_{exp.id}', exp.bullets)
        exp.is_current = request.POST.get(f'exp_current_{exp.id}') == 'on'
        exp.save()

    # Update Competencies
    for comp in resume.competencies.all():
        comp.icon = request.POST.get(f'comp_icon_{comp.id}', comp.icon)
        comp.title = request.POST.get(f'comp_title_{comp.id}', comp.title)
        comp.description = request.POST.get(f'comp_desc_{comp.id}', comp.description)
        comp.save()

    messages.success(request, "Resume updated successfully!")
    return redirect('core:resume')


@login_required
def export_resume_pdf(request):
    """Generates a PDF of the resume for superusers only"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("You do not have permission to export the resume.")

    resume, _ = ResumeProfile.objects.get_or_create(id=1)
    template = get_template('core/partials/resume_content.html')

    # We pass 'exporting_pdf' so we can hide buttons in the PDF template
    html = template.render({'resume': resume, 'exporting_pdf': True}, request)

    # Create PDF
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)

    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{resume.name.replace(" ", "_")}_Resume.pdf"'
        return response
    return HttpResponse("Error generating PDF", status=400)
