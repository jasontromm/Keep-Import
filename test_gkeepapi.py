import sys
try:
    import gkeepapi
    print("gkeepapi imported successfully!")
    print("Version:", getattr(gkeepapi, "__version__", "unknown"))
    keep = gkeepapi.Keep()
    print("Keep object initialized successfully!")
except Exception as e:
    print("Error importing/initializing gkeepapi:", e)
    sys.exit(1)
