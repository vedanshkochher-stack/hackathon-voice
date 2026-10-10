"""Related products for a buyer: pc_item names in an in-memory FAISS index, matched against the buyer's
current lead and the products they liked / viewed, all read from their context file (buyer.md).

  data/item/items.csv.csv (glcat_mcat_name) -> name vectors (all-MiniLM-L6), built once in chunks and saved
  under data/item/ -> loaded into an in-memory FAISS index at server start (python -m relprod builds it)
  for_buyer(meta) -> top 3, optionally grounded with Google search for the lead
"""
from .store import (RelatedStore, buyer_inputs, for_buyer, get_store, load_or_build, prefetch, same_product, set_store,
                    short_name, start_loading, status)

__all__ = ["RelatedStore", "buyer_inputs", "for_buyer", "get_store", "load_or_build", "prefetch", "same_product",
           "set_store", "short_name", "start_loading", "status"]
