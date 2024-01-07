/**
 * @typedef {Object} Page
 * @property {string} name - The name of the page.
 * @property {string} menu - The menu of the page belong to.
 * @property {string} url - The page slug
 * @property {string[]} tags - The tags associated with the page.
 * @property {string} date - The date of the page.
 */

/**
 * @typedef {Object} GNode
 * @property {string} id - the node id
 * @property {boolean} isMenu - indicate is node is a menu
 * @property {string} title - the node title
 * @property {number} references - number of realted pages
 *
 */
function renderGraph() {
  // Configs
  const NODE_COLOR = "#e13F5e";
  const LINK_COLOR = "#9B9B9B";
  const HIGHLIGHT_COLOR = "#e13F5e";
  const MAX_FONT_SIZE = 16;
  const MIN_FONT_SIZE = 8;
  const MAX_DISTANCE = 350;
  const MIN_DISTANCE = 150;
  const MIN_REF_COUNT = 5; // fake ref count to make sure node have minium size
  const TAG_COUNT_BUFFER = 5; // buffer ref count tags has bigger size
  const MENU_COUNT_BUFFER = 10; // buffer ref count to make menu has bigger size
  const MIN_ZOOM_LEVEL = 0.1;
  const MAX_ZOOM_LEVEL = 5;
  const HOVER_COLOR_OPACITY = 0.15;
  const HOVER_SCALE_RATIO = 1.1;
  const SHOW_TEXT_AT_SCALE = 1.1;
  const DEFAULT_ZOOM_LEVEL = 0.2;
  const AUTO_HIDE_LABEL_THRESHOLD = 50; // 50 nodes

  // state
  let dragging = false;
  let forceShowLabel = false;

  // get container size
  const graphContainer = document.querySelector(".graph-container");
  const isFullscreen = graphContainer.classList.contains("fullscreen");
  const h = graphContainer.clientHeight / 2;
  const w = graphContainer.clientWidth / 2;

  // utilities
  function uniqBy(arr, prop) {
    const uniqueObjects = {};
    const result = arr.filter((obj) => {
      if (!uniqueObjects[obj[prop]]) {
        uniqueObjects[obj[prop]] = true;
        return true;
      }
      return false;
    });
    return result;
  }

  function groupBy(array, property) {
    return array.reduce((acc, obj) => {
      const key = obj[property];
      if (!acc[key]) {
        acc[key] = [];
      }
      acc[key].push(obj);
      return acc;
    }, {});
  }

  const isInDardMod = (fn) => {
    if (!window.matchMedia) return;

    const query = window.matchMedia("(prefers-color-scheme: dark)");
    fn(query.matches);

    query.addEventListener("change", (event) => fn(event.matches));
  };

  /**
   * @type {Page[]}
   */
  const pages = JSON.parse(
    document.querySelector(".pagenav").attributes["x-data"]?.value || "",
  );

  const currentSlug = window.location.pathname;
  const currentMenu = currentSlug.split("/").filter(Boolean)[0];

  /**
   * @type {Record<string, Page[]}
   */
  const pagesByMenus = groupBy(pages, "menu");

  /**
   * Find related pages based on tags.
   * @param {string[]} currentTags - Tags of the current page.
   * @returns {Page[]} Array of related pages.
   */
  function findRelatedPages(currentTags) {
    // Filter pages based on at least one matching tag
    const relatedPages = pages.filter((page) => {
      return (page.tags || []).some((tag) => currentTags.includes(tag));
    });

    // Remove the current page from the related pages, if it exists in the list
    const currentPageIndex = relatedPages.findIndex(
      (page) => page.tags === currentTags,
    );
    if (currentPageIndex !== -1) {
      relatedPages.splice(currentPageIndex, 1);
    }

    return relatedPages;
  }

  /**
   *
   * @returns {Page} the page
   */
  function findPageBySlug(slug) {
    return pages.filter((page) => page.url === slug)[0];
  }

  function groupPagesByTags(allPages = []) {
    const groupedPages = {};
    allPages.forEach((page) => {
      (page.tags || []).forEach((tag) => {
        if (!groupedPages[tag]) {
          groupedPages[tag] = [];
        }
        groupedPages[tag].push(page);
      });
    });

    return groupedPages;
  }

  /**
   * Get a random number within a specific range.
   * @param {number} min - The minimum value of the range.
   * @param {number} max - The maximum value of the range.
   * @returns {number} Random number within the range.
   */
  function getRandomNumberInRange(min, max) {
    return Math.round(Math.random() * (max - min) + min);
  }
  // ============================================ DATA PROCESS LOGIC =========================================== //

  const currentPage = findPageBySlug(currentSlug);

  // Data for render
  /**
   * @type {GNode}
   */
  let gNodes = [];
  let nodeLinks = [];
  if (currentPage) {
    const relatedPages = findRelatedPages(currentPage.tags);
    gNodes = [
      {
        id: currentPage.url,
        title: currentPage.name,
        references: MIN_REF_COUNT + relatedPages.length + MENU_COUNT_BUFFER,
        url: currentPage.url
      },
      ...relatedPages.map((pg) => ({
        id: pg.url,
        title: pg.name,
        references: MIN_REF_COUNT,
        url: pg.url
      })),
    ];

    gNodes = uniqBy(gNodes, "id");

    nodeLinks = relatedPages.map((pg) => ({
      source: pg.url,
      target: currentPage.url,
    }));
  } else {
    // sub pages
    const subPages = pagesByMenus[currentMenu];
    const tags = groupPagesByTags(subPages);

    // make sure to reset nodes data
    gNodes = [];
    nodeLinks = [];
    for (let tag in tags) {
      gNodes = gNodes.concat(
        {
          id: tag,
          title: `#${tag}`,
          references: MIN_REF_COUNT + tags[tag].length + TAG_COUNT_BUFFER,
          url: `/tags/${tag}`
        },
        ...tags[tag].map((pg) => ({
          id: pg.url,
          title: pg.name,
          references: MIN_REF_COUNT,
          url: pg.url,
        })),
      );

      nodeLinks = nodeLinks.concat(
        tags[tag].map((pg) => ({
          source: pg.url,
          target: tag,
        })),
      );
    }
  }
  gNodes = uniqBy(gNodes, "id");

  if (!gNodes.length) {
    document.querySelector(".graph-container").classList.add("hidden");
    return;
  }

  let canShowAllLabels = gNodes.length < AUTO_HIDE_LABEL_THRESHOLD;

  // ============================================ GRAPH DRAWING  =========================================== //
  const svg = d3.select(".graph-container>svg");
  const container = svg.append("g");

  // Scale for node size based on references
  const sizeScale = d3
    .scaleLinear()
    .domain([1, d3.max(gNodes, (d) => d.references || MIN_REF_COUNT)])
    .range([4, 24]);

  function forceSimulation() {
    return d3
      .forceSimulation(gNodes)
      .force(
        "charge",
        d3
          .forceManyBody()
          .strength((d) => -50 * sizeScale(d.references || MIN_REF_COUNT)),
      )
      .force(
        "link",
        d3
          .forceLink(nodeLinks)
          .id((d) => d.id)
          .distance((d) => {
            const referenceCount = d.source.references + d.target.references;
            // Cap the distance for nodes with a large number of links
            const dynamicDistance = getRandomNumberInRange(
              MIN_DISTANCE,
              MAX_DISTANCE +
              (referenceCount > 50 ? referenceCount * 2 : referenceCount * 3),
            );
            return Math.min(dynamicDistance, MAX_DISTANCE + referenceCount * 5);
          }),
      )
      .force("center", d3.forceCenter(w, h));
  }

  let simulation = forceSimulation();

  const link = container
    .selectAll("line")
    .data(nodeLinks)
    .enter()
    .append("line")
    .attr("stroke", LINK_COLOR);

  const label = container
    .selectAll("text")
    .data(gNodes)
    .enter()
    .append("text")
    .text((d) => d.title)
    .attr("x", 8)
    .attr("y", 3)
    .attr("class", "svg-label")
    .style("font-size", "12px")
    .style("visibility", canShowAllLabels ? "visible" : "hidden");

  const node = container
    .selectAll("circle")
    .data(gNodes)
    .enter()
    .append("circle")
    .attr("r", (d) => sizeScale(d.references || MIN_REF_COUNT))
    .attr("fill", NODE_COLOR)
    .on("mouseover", handleMouseOver)
    .on("mouseout", handleMouseOut);

  simulation.nodes(gNodes).on("tick", () => {
    link
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);

    node
      .attr("cx", (d) => d.x)
      .attr("cy", (d) => d.y)
      .attr("r", (d) => sizeScale(d.references || MIN_REF_COUNT));

    label
      .attr("x", (d) => d.x)
      // Position text below the circle (adjust the offset as needed)
      .attr("y", (d) => d.y + sizeScale(d.references || MIN_REF_COUNT) + 25)
      .attr("text-anchor", "middle");
  });

  function zoomed(event) {
    const transform = event.transform;
    container.attr("transform", transform);

    if (transform.k > SHOW_TEXT_AT_SCALE) {
      forceShowLabel = true;
      label.style("visibility", "visible");
    } else {
      label.style("visibility", canShowAllLabels ? "visible" : "hidden");
      forceShowLabel = false;
    }

    label.style(
      "font-size",
      `${Math.max(
        MAX_FONT_SIZE / (transform.k > 0.4 ? transform.k : 0.4),
        MIN_FONT_SIZE,
      )}px`,
    );
  }

  const zoom = d3
    .zoom()
    .scaleExtent([MIN_ZOOM_LEVEL, MAX_ZOOM_LEVEL])
    .on("zoom", zoomed);

  svg.call(zoom);
  svg.call(zoom.scaleTo, DEFAULT_ZOOM_LEVEL);

  function isConnected(a, b) {
    // Logic to check if nodes are connected (modify as per your data structure)
    return nodeLinks.some(
      (link) =>
        (link.source === a && link.target === b) ||
        (link.source === b && link.target === a),
    );
  }

  function handleMouseOver(event, d) {
    if (dragging) {
      return;
    }
    const connectedLinks = link.filter(
      (link) => link.source === d || link.target === d,
    );

    d3.select(this).attr(
      "r",
      sizeScale(d.references || MIN_REF_COUNT) * HOVER_SCALE_RATIO,
    );
    d3.select(this.nextElementSibling).style("visibility", "visible");
    // Highlight the hovered node

    // Show the title of the hovered node
    label.filter((nodeData) => nodeData === d).style("visibility", "visible");
    label.filter((nodeData) => nodeData !== d).style("visibility", "hidden");

    // Show titles of connected nodes
    connectedLinks.each(function (linkData) {
      const connectedNode =
        linkData.source === d ? linkData.target : linkData.source;
      label
        .filter((nodeData) => nodeData === connectedNode)
        .style("visibility", "visible");
    });

    // Highlight the connected links
    connectedLinks.attr("stroke", HIGHLIGHT_COLOR); // Highlight connected links

    // Fade out unconnected nodes
    node
      .filter((nodeData) => nodeData !== d && !isConnected(d, nodeData))
      .attr("fill-opacity", HOVER_COLOR_OPACITY);

    // Fade out unconnected links
    link
      .filter((linkData) => linkData.source !== d && linkData.target !== d)
      .attr("stroke-opacity", HOVER_COLOR_OPACITY);
  }

  function handleMouseOut(event, d) {
    if (dragging) {
      return;
    }

    d3.select(this).attr("r", sizeScale(d.references || MIN_REF_COUNT));
    // d3.select(this.nextElementSibling).style("visibility", "hidden");

    // Hide titles of connected nodes and the hovered node
    if (forceShowLabel) {
      label.style("visibility", "visible");
    } else {
      label.style("visibility", canShowAllLabels ? "visible" : "hidden");
    }

    // Restore default link colors
    link.attr("stroke", LINK_COLOR);

    // Restore opacity of unconnected nodes
    node.attr("fill-opacity", 1);

    // Restore opacity of unconnected links
    link.attr("stroke-opacity", 1);
  }

  function dragstarted(event, d) {
    dragging = true;
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;

    // Highlight the dragged node
    d3.select(this)
      .attr("r", sizeScale(d.references || MIN_REF_COUNT) * HOVER_SCALE_RATIO)
      .attr("fill", HIGHLIGHT_COLOR);

    label.filter((nodeData) => nodeData === d).style("visibility", "visible");
  }

  function dragged(event, d) {
    dragging = true;
    d.fx = event.x;
    d.fy = event.y;
  }

  function dragended(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;

    dragging = false;
  }

  const drag = d3
    .drag()
    .on("start", dragstarted)
    .on("drag", dragged)
    .on("end", dragended);

  node.call(drag);

  // Attach click event listener to nodes
  node.on("click", function (event, d) {
    // Redirect to the URL associated with the node when clicked
    window.location.href = d.url;
  });
};


// initial render graph
setTimeout(() => {
  renderGraph();
}, 150);

window.$graphCenterNodes = function () {
  const svg = d3.select(".graph-container > svg");
  svg.selectAll("*").remove();

  // Reset zoom behavior and transform
  const zoom = d3.zoom().on("zoom", null);
  svg.call(zoom.transform, d3.zoomIdentity);

  // Reset drag behavior
  const drag = d3.drag().on("start", null).on("drag", null).on("end", null);
  svg.selectAll("circle").call(drag);

  setTimeout(() => {
    renderGraph();
  }, 150);
};
