"""Unit tests for the ingest and search Lambdas, with SageMaker and S3 Vectors mocked."""

import io
import json
from unittest.mock import MagicMock

import pytest

import ingest_s3vectors as ingest
import search_s3vectors as search


def sagemaker_returning(payload):
    client = MagicMock()
    client.invoke_endpoint.side_effect = lambda **kwargs: {"Body": io.BytesIO(json.dumps(payload).encode())}
    return client


@pytest.mark.parametrize("module", [ingest, search])
@pytest.mark.parametrize(
    "payload, expected",
    [
        ([[[0.1, 0.2]]], [0.1, 0.2]),  # HuggingFace feature-extraction shape
        ([[0.3, 0.4]], [0.3, 0.4]),
        ([0.5, 0.6], [0.5, 0.6]),
    ],
)
def test_get_embedding_unwraps_nested_arrays(monkeypatch, module, payload, expected):
    monkeypatch.setattr(module, "sagemaker_runtime", sagemaker_returning(payload))
    assert module.get_embedding("hello") == expected


@pytest.fixture
def aws(monkeypatch):
    s3v = MagicMock()
    s3v.query_vectors.return_value = {
        "vectors": [{"key": "v1", "distance": 0.12, "metadata": {"text": "Apple earnings", "topic": "AAPL"}}]
    }
    for module in (ingest, search):
        monkeypatch.setattr(module, "sagemaker_runtime", sagemaker_returning([[[0.1, 0.2]]]))
        monkeypatch.setattr(module, "s3_vectors", s3v)
    return s3v


def test_ingest_stores_vector_with_metadata(aws):
    event = {"body": json.dumps({"text": "Apple beat earnings", "metadata": {"topic": "AAPL"}})}
    response = ingest.lambda_handler(event, None)

    assert response["statusCode"] == 200
    document_id = json.loads(response["body"])["document_id"]
    kwargs = aws.put_vectors.call_args.kwargs
    vector = kwargs["vectors"][0]
    assert kwargs["vectorBucketName"] == ingest.VECTOR_BUCKET
    assert vector["key"] == document_id
    assert vector["data"] == {"float32": [0.1, 0.2]}
    assert vector["metadata"]["text"] == "Apple beat earnings"
    assert vector["metadata"]["topic"] == "AAPL"
    assert "timestamp" in vector["metadata"]


def test_ingest_accepts_dict_body(aws):
    assert ingest.lambda_handler({"body": {"text": "hi"}}, None)["statusCode"] == 200


def test_ingest_requires_text(aws):
    response = ingest.lambda_handler({"body": json.dumps({"metadata": {}})}, None)
    assert response["statusCode"] == 400
    aws.put_vectors.assert_not_called()


def test_ingest_returns_500_on_aws_error(aws):
    aws.put_vectors.side_effect = RuntimeError("bucket missing")
    response = ingest.lambda_handler({"body": {"text": "hi"}}, None)
    assert response["statusCode"] == 500
    assert "bucket missing" in response["body"]


def test_search_returns_formatted_results(aws):
    response = search.lambda_handler({"body": json.dumps({"query": "apple", "k": 3})}, None)
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body == {
        "results": [{"id": "v1", "score": 0.12, "text": "Apple earnings", "metadata": {"text": "Apple earnings", "topic": "AAPL"}}],
        "count": 1,
    }
    assert aws.query_vectors.call_args.kwargs["topK"] == 3


def test_search_defaults_k_to_5(aws):
    search.lambda_handler({"body": {"query": "apple"}}, None)
    assert aws.query_vectors.call_args.kwargs["topK"] == 5


def test_search_requires_query(aws):
    assert search.lambda_handler({"body": {}}, None)["statusCode"] == 400
