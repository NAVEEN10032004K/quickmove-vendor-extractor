"""Thin TypeSafe Jev wrapper. If the API shape changes, only this file changes."""
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

_TYPES = {"choice": Choice, "noul": Noul, "score": Score}
_client = None  # reads TYPESAFE_API_KEY from env on first use


def t(message: str, schema: dict) -> dict:
    """Ask Jev `schema` (raw /v1/systemone `questions` dict) about `message`.

    Returns {name: value} where value is the chosen option (choice), the score (score)
    or the yes-probability 0-1 (noul). Choice/score also add {name}_confidence.
    """
    global _client
    _client = _client or TypeSafeClient(model="jev-latest")
    questions = {k: _TYPES[q["type"]](**q) for k, q in schema.items()}
    answers = _client.system_one(state=message, questions=questions).answers
    out = {}
    for name, a in answers.items():
        if a.type == "choice":
            out[name], out[f"{name}_confidence"] = a.choice, a.confidence
        elif a.type == "score":
            out[name], out[f"{name}_confidence"] = a.score, a.confidence
        else:
            out[name] = a.noul
    return out


if __name__ == "__main__":
    from dotenv import load_dotenv

    from app.prompts import JEV_QUESTIONS

    load_dotenv()
    print(t("Sir quote: 3BHK Mumbai to Pune Rs 18000, advance 50% do, valid today only. No GST bill.", JEV_QUESTIONS))
