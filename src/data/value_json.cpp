// The one place that turns a Value into JSON and back. Keeping the parser in
// a single translation unit is what lets the public headers stay free of it.

#include <retrolarium/core/value.hpp>

#include <nlohmann/json.hpp>

namespace retrolarium::core {
namespace {

using Json = nlohmann::json;

Value fromJson(const Json &value)
{
    switch (value.type()) {
    case Json::value_t::null:
        return Value();
    case Json::value_t::boolean:
        return Value::boolean(value.get<bool>());
    case Json::value_t::number_integer:
    case Json::value_t::number_unsigned:
        return Value::integer(value.get<std::int64_t>());
    case Json::value_t::number_float:
        return Value::real(value.get<double>());
    case Json::value_t::string:
        return Value::string(value.get<std::string>());
    case Json::value_t::array: {
        std::vector<Value> items;
        items.reserve(value.size());
        for (const Json &item : value) {
            items.push_back(fromJson(item));
        }
        return Value::array(std::move(items));
    }
    case Json::value_t::object: {
        std::map<std::string, Value> members;
        for (auto entry = value.begin(); entry != value.end(); ++entry) {
            members.emplace(entry.key(), fromJson(entry.value()));
        }
        return Value::object(std::move(members));
    }
    default:
        throw ValueError("unsupported JSON value");
    }
}

Json toJson(const Value &value)
{
    switch (value.kind()) {
    case Value::Kind::Null:
        return nullptr;
    case Value::Kind::Boolean:
        return value.asBoolean();
    case Value::Kind::Integer:
        return value.asInteger();
    case Value::Kind::Double:
        return value.asDouble();
    case Value::Kind::String:
        return value.asString();
    case Value::Kind::Array: {
        Json array = Json::array();
        for (const Value &item : value.asArray()) {
            array.push_back(toJson(item));
        }
        return array;
    }
    case Value::Kind::Object: {
        Json object = Json::object();
        for (const auto &entry : value.asObject()) {
            object[entry.first] = toJson(entry.second);
        }
        return object;
    }
    }
    return nullptr;
}

} // namespace

Value parseValue(const std::string &json)
{
    try {
        return fromJson(Json::parse(json));
    } catch (const Json::exception &error) {
        throw ValueError(std::string("value is not valid JSON: ") + error.what());
    }
}

std::string renderValue(const Value &value)
{
    // nlohmann's default object type is std::map, so this emits sorted keys, a
    // two-space indent and non-ASCII escaped, exactly as json.dumps does.
    return toJson(value).dump(2, ' ', true);
}

} // namespace retrolarium::core
