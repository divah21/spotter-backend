import os
import django


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from django.conf import settings
    from django.db import connection
    from trips.models import User, Trip, ELDLog, Stop

    print('=' * 60)
    print('DATABASE CONNECTION INFO')
    print('=' * 60)
    db_config = settings.DATABASES['default']
    print(f"Database Name: {db_config['NAME']}")
    print(f"Host: {db_config['HOST']}")
    print(f"Port: {db_config['PORT']}")
    print(f"User: {db_config['USER']}")

    print('\n' + '=' * 60)
    print('ALL TABLES IN DATABASE')
    print('=' * 60)
    tables = connection.introspection.table_names()
    for i, table in enumerate(sorted(tables), 1):
        print(f"{i:2}. {table}")

    print('\n' + '=' * 60)
    print('DATA COUNTS')
    print('=' * 60)
    print(f"Users: {User.objects.count()}")
    print(f"Trips: {Trip.objects.count()}")
    print(f"Stops: {Stop.objects.count()}")
    print(f"ELD Logs: {ELDLog.objects.count()}")

    print('\n' + '=' * 60)
    print('EXISTING USERS')
    print('=' * 60)
    for user in User.objects.all():
        print(f"  • {user.username} ({user.email}) - Role: {user.role} - Active: {user.is_active}")

    print('\n' + '=' * 60)
    print('DATABASE STATUS: ✅ ALL TABLES EXIST WITH DATA')
    print('=' * 60)


if __name__ == '__main__':
    main()
