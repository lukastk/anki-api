from anki import collection_pb2

from anki_api.schemas.common import Mutation, OpChangesModel, mutation, op_changes


def test_op_changes_maps_all_flags():
    proto = collection_pb2.OpChanges(card=True, note=True, study_queues=True)
    model = op_changes(proto)
    assert isinstance(model, OpChangesModel)
    assert model.card is True
    assert model.note is True
    assert model.study_queues is True
    assert model.deck is False  # untouched flags default false


def test_op_changes_covers_every_proto_field():
    # Guard against the proto gaining a field we forget to mirror.
    proto_fields = {f.name for f in collection_pb2.OpChanges.DESCRIPTOR.fields}
    model_fields = set(OpChangesModel.model_fields)
    assert proto_fields == model_fields


def test_mutation_with_id_stringifies():
    proto = collection_pb2.OpChanges(deck=True)
    m = mutation(proto, id=1781013713142)
    assert isinstance(m, Mutation)
    assert m.id == "1781013713142"
    assert m.count is None
    assert m.changes.deck is True


def test_mutation_with_count():
    proto = collection_pb2.OpChanges(card=True)
    m = mutation(proto, count=5)
    assert m.count == 5
    assert m.id is None


def test_mutation_noop_all_false():
    m = mutation(collection_pb2.OpChanges())
    assert not any(getattr(m.changes, f) for f in OpChangesModel.model_fields)
