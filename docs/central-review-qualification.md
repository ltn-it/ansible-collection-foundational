# Central review qualification

The protected consumer configuration reached Main through pull request #671,
commit `e41fe78a53553b0d5dcde3ea42d8999968747f41`. Its existing lint, Molecule,
and package build/install checks remain mandatory.

Admission requires the independently selected central Source and this
repository's own native Release App qualification: a completed Draft rejection,
one finalized positive review, byte-identical replay without another funded
request, and a normal Main promotion with a genuine native approval.

This record describes the qualification contract. Successful configuration
bootstrap alone does not establish qualification, enforcement, or publication.

## Preserve the native replay evidence

Rerun the successful `Protected current revision` job through the native
`POST /repos/{owner}/{repo}/actions/jobs/{job_id}/rerun` endpoint. Keep the
original native receipt artifact available and compare the metadata, complete
request, and response hashes with the replay. A full workflow restart removes
prior attempt artifacts and cannot supply this unchanged replay evidence.
