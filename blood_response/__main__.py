from .cli import main

try:
    main()
except KeyboardInterrupt:
    print("Stopped.")
except (ValueError, FileExistsError) as error:
    raise SystemExit(str(error)) from None
