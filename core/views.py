from django.http import JsonResponse

def assetlinks_view(request):
    """Serve the assetlinks.json file for Android App Links."""
    data = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": "com.example.espere_app",
            "sha256_cert_fingerprints": [
                # TODO: Replace with the actual SHA-256 fingerprint from Play Console / Keystore
                "FA:C6:17:45:D2:2C:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34"
            ]
        }
    }]
    return JsonResponse(data, safe=False)
