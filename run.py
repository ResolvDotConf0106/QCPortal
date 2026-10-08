from app import create_app

app = create_app()

if __name__ == '__main__':
    print("Starting KVM Host QC Portal on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
