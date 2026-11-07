# Deployment guide — Render

1. Upload the contents of this folder to the root of a GitHub repository. The root must contain `app.py`, `requirements.txt`, `render.yaml`, and the `static/` folder.
2. In Render, select **New → Blueprint** and connect the GitHub repository.
3. Review the detected service and apply the blueprint.
4. In the Render service's Environment settings, set `OPENAI_API_KEY` to a newly generated secret key. Never commit `.env` or expose the key in browser code.
5. Deploy and wait for the service to report **Live**.
6. Verify `https://YOUR-SERVICE.onrender.com/api/health` returns `{"status":"ok","service":"crypto-intelligence-platform"}` and open the service root URL.

The Render plan configured in `render.yaml` may be billable. Check current pricing in Render before applying. OpenAI API usage is billed separately. If Render's blueprint editor requires a different plan selection, choose an available plan in its dashboard.
