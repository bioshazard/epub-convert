function Link(el) return el.content end
function Image(el) return el.caption end
function Div(el) return el.content end
function Span(el) return el.content end
function RawBlock(el) return {} end
function RawInline(el) return {} end

function Superscript(el) return el.content end
function Subscript(el) return el.content end
function Table(el)
  local simple = pandoc.utils.to_simple_table(el)
  for i, _ in ipairs(simple.widths) do simple.widths[i] = 0 end
  local caption = simple.caption
  simple.caption = {}
  local function cell(blocks)
    local function boundary(el)
      el.content:insert(pandoc.Space())
      return el
    end
    local spaced = pandoc.Div(blocks):walk({Plain=boundary, Para=boundary})
    local inlines = pandoc.utils.blocks_to_inlines(spaced.content, {pandoc.Space()})
    local flat = pandoc.Span(inlines):walk({LineBreak = function() return pandoc.Space() end})
    return {pandoc.Plain(flat.content)}
  end
  for i, blocks in ipairs(simple.headers) do simple.headers[i] = cell(blocks) end
  for _, row in ipairs(simple.rows) do
    for i, blocks in ipairs(row) do row[i] = cell(blocks) end
  end
  local result = pandoc.utils.from_simple_table(simple)
  if #caption > 0 then return {pandoc.Para(caption), result} end
  return result
end

function CodeBlock(el)
  if #el.classes == 0 then el.classes = {"text"} end
  return el
end

-- Font/style spans can split one word or list marker into adjacent Str nodes.
-- Coalesce those fragments before the writer decides what needs escaping.
local function merge_text(inlines)
  local result = pandoc.List()
  for _, inline in ipairs(inlines) do
    local previous = result[#result]
    if previous and previous.t == "Str" and inline.t == "Str" then
      previous.text = previous.text .. inline.text
    else
      result:insert(inline)
    end
  end
  return result
end

return {
  {Link=Link, Image=Image, Div=Div, Span=Span, RawBlock=RawBlock, RawInline=RawInline,
   Superscript=Superscript, Subscript=Subscript, Table=Table, CodeBlock=CodeBlock},
  {Inlines=merge_text}
}
