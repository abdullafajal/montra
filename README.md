# Montra - Expense & Income Tracker

A modern, mobile-first Expense & Income Tracker built with Django and Tailwind CSS. Features a PWA implementation for installable app experience.

## Features

- **Dashboard**: Visual overview of your finances with charts.
- **Transactions**: Add income and expenses with categories.
- **Budgets**: Set monthly budgets for categories.
- **Savings Goals**: Track progress towards financial goals.
- **Reports**: Detailed financial reports and exports (PDF/CSV).
- **PWA**: Installable on Android and iOS with offline support.
- **Theme**: Dark/Light mode support (Material 3 Design).

## Setup

### Prerequisites
- Python 3.13+
- `uv` (recommended package manager) or `pip`

### Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd montra
    ```

2.  **Install dependencies**:
    ```bash
    uv sync
    # or
    pip install -r requirements.txt (if generated)
    ```

3.  **Apply migrations**:
    ```bash
    uv run python manage.py migrate
    ```

4.  **Create superuser**:
    ```bash
    uv run python manage.py createsuperuser
    ```

5.  **Run server**:
    ```bash
    uv run python manage.py runserver
    ```

## PWA Features

This project is configured as a Progressive Web App.
- **Manifest**: `/manifest.json`
- **Service Worker**: `/serviceworker.js`
- **Icons**: Generated icons in `static/images/icons/`

### Generating Icons
If you update the source logo at `static/images/logo.png`, regenerate the PWA icons using:
```bash
uv run python manage.py generate_pwa_icons
```

## Management Commands
- `seed_categories`: Populates default categories.
- `seed_demo_data`: Generates demo transactions for testing.

## Technologies
- Django 5.1
- Tailwind CSS (via CDN for dev)
- Chart.js
- Chart.js
- Django PWA

## Deployment (PythonAnywhere)

1.  **Pull code**:
    ```bash
    git pull origin main
    ```

2.  **Update dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Migrate database**:
    ```bash
    python manage.py migrate
    ```

4.  **Collect Static Files** (Fixes 404 errors):
    ```bash
    python manage.py collectstatic
    ```
    This gathers all static files (CSS, JS, Images) into the `staticfiles` directory.

5.  **Configure Static Mapping** (Web Tab):
    - **URL**: `/static/`
    - **Directory**: `/home/<username>/<project_folder>/staticfiles` (e.g., `/home/montra/montra/staticfiles`)

6.  **Environment Variables**:
    Create a `.env` file in your project root with production settings (DEBUG=False).
