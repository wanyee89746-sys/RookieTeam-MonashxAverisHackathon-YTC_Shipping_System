from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health_check():  
    """This function is to check whether the API server is running."""
    return {"status": "ok"}