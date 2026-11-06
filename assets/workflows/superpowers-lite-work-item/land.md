Land the approved attempt on the item's target branch. Run:

    gc superpowers-lite land

It moves the target branch by compare-and-swap and closes this step, or closes
it as failed when the target moved in a way it cannot land on. Exit when it
returns. Do not run git yourself.
